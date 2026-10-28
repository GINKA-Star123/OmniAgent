from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
import uuid
from collections import Counter
from pathlib import Path

import httpx

from aiagent.evaluation.http_support import require_isolated
from aiagent.evaluation.metrics import quantile
from aiagent.knowledge.evaluation.answer import evaluate_answer


def load_summary(rows: list[dict], seconds: float, slo_ms: float) -> dict:
    if seconds <= 0 or not rows:
        raise ValueError("nonempty rows and positive observation window required")
    attempted = [row for row in rows if row["sent"]]
    completed = [row for row in rows if row["state"] == "completed"]
    received = [row for row in rows if row.get("received", row["state"] == "completed")]
    successful_latency = [row["elapsed_ms"] for row in completed if row["http_2xx"]]
    attempt_elapsed = [row["elapsed_ms"] for row in attempted]
    good = [row for row in completed if row["http_2xx"] and row["rule_ok"] and row["elapsed_ms"] <= slo_ms]
    return {
        "total_scheduled": len(rows), "window_seconds_including_drain": seconds,
        "sent_qps": len(attempted) / seconds, "completed_qps": len(received) / seconds,
        "http_2xx_qps": sum(row["http_2xx"] for row in attempted) / seconds,
        "rule_goodput_qps": len(good) / seconds, "rule_slo_pass_rate": len(good) / len(rows),
        "failure_rate": 1 - len(good) / len(rows), "states": dict(Counter(row["state"] for row in rows)),
        "successful_http_latency_ms": {f"p{int(q * 100)}": quantile(successful_latency, q) for q in (.5, .95, .99)},
        "attempt_elapsed_ms_censored": {f"p{int(q * 100)}": quantile(attempt_elapsed, q) for q in (.5, .95, .99)},
        "successful_latency_n": len(successful_latency), "p99_small_sample": len(successful_latency) < 1000,
        "timeout_n": sum(row["state"] in {"timeout", "queue_timeout"} for row in rows),
        "semantic_goodput": None, "server_admitted_qps": None,
    }

async def run_load(*, rate: float, total: int, workers: int, queue_size: int, users: int,
                   timeout: float, slo_ms: float, text: str, required: tuple[str, ...],
                   forbidden: tuple[str, ...], warmup: int = 0,
                   transport: httpx.AsyncBaseTransport | None = None) -> dict:
    base = require_isolated()
    if (not math.isfinite(rate) or rate <= 0 or not 1 <= total <= 100000 or not 1 <= workers <= 1000
            or not 1 <= queue_size <= 100000 or not 1 <= users <= 1000 or warmup < 0
            or not math.isfinite(timeout) or timeout <= 0 or not math.isfinite(slo_ms) or slo_ms <= 0):
        raise ValueError("invalid load parameters")
    if not required or any(not term.strip() for term in required):
        raise ValueError("load quality checks require nonblank required terms")
    evaluate_answer("validation", required_terms=required, forbidden_terms=forbidden)
    prefix = "eval-load-" + uuid.uuid4().hex[:12]
    headers = {"Authorization": f"Bearer {os.environ['EVAL_API_TOKEN']}"} if os.environ.get("EVAL_API_TOKEN") else {}
    client_kwargs = dict(base_url=base, headers=headers, trust_env=False, follow_redirects=False,
                         timeout=timeout, limits=httpx.Limits(max_connections=workers, max_keepalive_connections=workers))
    if transport is not None:
        client_kwargs["transport"] = transport
    queue = asyncio.Queue(maxsize=queue_size)
    rows, touched_users = [], set()
    tasks = []
    async with httpx.AsyncClient(**client_kwargs) as client:
        async def perform(index: int, due: float, *, keep: bool = True):
            user = f"{prefix}-{index % users}"
            touched_users.add(user)
            row = {"index": index, "sent": False, "http_2xx": False, "rule_ok": False,
                   "state": "queue_timeout", "elapsed_ms": 0.0, "received": False}
            remaining = timeout - (time.perf_counter() - due)
            try:
                if remaining > 0:
                    row["sent"] = True
                    response = await asyncio.wait_for(client.post("/chat", json={
                        "user_id": user, "username": "合成负载用户", "text": text,
                        "session_id": f"{user}-request-{index}",
                    }), timeout=remaining)
                    row["state"] = "completed"
                    row["received"] = True
                    row["http_2xx"] = 200 <= response.status_code < 300
                    row["status_code"] = response.status_code
                    if row["http_2xx"]:
                        body = response.json()
                        answer = body.get("reply")
                        if body.get("ok") is True and isinstance(answer, str):
                            row["rule_ok"] = evaluate_answer(answer, required_terms=required,
                                                             forbidden_terms=forbidden).passed
            except (TimeoutError, httpx.TimeoutException):
                row["state"] = "timeout"
            except Exception as exc:
                row["state"] = "error"
                row["error_type"] = type(exc).__name__
            row["elapsed_ms"] = (time.perf_counter() - due) * 1000
            if keep:
                rows.append(row)

        async def worker():
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    await perform(*item)
                finally:
                    queue.task_done()

        cleanup_failures = 0
        try:
            for index in range(warmup):
                await perform(-index - 1, time.perf_counter(), keep=False)
            tasks = [asyncio.create_task(worker()) for _ in range(workers)]
            started = time.perf_counter()
            for index in range(total):
                due = started + index / rate
                await asyncio.sleep(max(0.0, due - time.perf_counter()))
                try:
                    queue.put_nowait((index, due))
                except asyncio.QueueFull:
                    rows.append({"index": index, "sent": False, "http_2xx": False, "rule_ok": False,
                                 "state": "dropped", "elapsed_ms": (time.perf_counter() - due) * 1000})
            await queue.join()
            for _ in tasks:
                await queue.put(None)
            await asyncio.gather(*tasks)
            duration = time.perf_counter() - started
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            for user in sorted(touched_users):
                try:
                    response = await asyncio.wait_for(client.delete(f"/memory/user/{user}"), timeout=timeout)
                    if response.status_code != 200 or response.json().get("ok") is not True:
                        cleanup_failures += 1
                except Exception:
                    cleanup_failures += 1
        report = load_summary(rows, duration, slo_ms)
        report.update(scope="isolated_api_open_loop_rule_quality", target_arrival_qps=rate, workers=workers,
                      max_queue=queue_size, users=users, warmup=warmup, timeout_seconds=timeout,
                      slo_ms=slo_ms, cleanup_failures=cleanup_failures, rows=sorted(rows, key=lambda row: row["index"]))
        return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Isolated open-loop chat load")
    parser.add_argument("--rate", type=float, required=True)
    parser.add_argument("--total", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--queue", type=int, default=100)
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--slo-ms", type=float, required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--required", action="append", required=True)
    parser.add_argument("--forbidden", action="append", default=[])
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--minimum-pass-rate", type=float, default=.95)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 0 <= args.minimum_pass_rate <= 1:
        parser.error("minimum pass rate must be in [0, 1]")
    if args.output.exists():
        parser.error("output already exists; choose a new evidence filename before making requests")
    report = asyncio.run(run_load(rate=args.rate, total=args.total, workers=args.workers, queue_size=args.queue,
                                  users=args.users, timeout=args.timeout, slo_ms=args.slo_ms, text=args.text,
                                  required=tuple(args.required), forbidden=tuple(args.forbidden), warmup=args.warmup))
    report["sut_identity"] = os.environ.get("EVAL_SUT_IDENTITY", "unspecified")
    report["ok"] = report["rule_slo_pass_rate"] >= args.minimum_pass_rate and not report["cleanup_failures"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"ok": report["ok"], "rule_goodput_qps": report["rule_goodput_qps"]}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
