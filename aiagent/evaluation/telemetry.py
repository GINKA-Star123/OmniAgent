from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sample a server PID, not the load generator")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--redis", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (not math.isfinite(args.seconds) or not math.isfinite(args.interval)
            or args.seconds <= 0 or args.interval <= 0 or args.pid <= 0):
        parser.error("PID, seconds and interval must be positive")
    import psutil

    process = psutil.Process(args.pid)
    created = process.create_time()
    process.cpu_percent(None)
    redis = None
    if args.redis:
        from redis import Redis

        url = os.environ.get("EVAL_TELEMETRY_REDIS_URL")
        if not url:
            parser.error("EVAL_TELEMETRY_REDIS_URL required")
        redis = Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    errors = 0
    try:
        with args.output.open("x", encoding="utf-8") as stream:
            while time.perf_counter() - start < args.seconds:
                row = {"time": datetime.now(UTC).isoformat(), "pid": args.pid}
                try:
                    if process.create_time() != created:
                        raise RuntimeError("server PID reused")
                    row.update(cpu_percent=process.cpu_percent(None), rss_bytes=process.memory_info().rss,
                               threads=process.num_threads())
                    if redis is not None:
                        info = redis.info()
                        row.update(redis_used_memory=info.get("used_memory"),
                                   redis_connected_clients=info.get("connected_clients"))
                except Exception as exc:
                    errors += 1
                    row["error_type"] = type(exc).__name__
                stream.write(json.dumps(row) + "\n")
                stream.flush()
                time.sleep(args.interval)
    finally:
        if redis is not None:
            redis.close()
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
