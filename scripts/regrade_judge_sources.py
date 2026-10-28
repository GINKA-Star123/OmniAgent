from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from aiagent.evaluation.contracts import Dataset, Observation, digest, read_json
from aiagent.evaluation.semantic import Judge


def regrade_report(report_path: Path, dataset_path: Path, kinds_path: Path | None = None) -> dict:
    """Replay only archived text judgments, never API observations or model requests."""
    original = read_json(report_path)
    dataset = Dataset.model_validate(read_json(dataset_path))
    conditions = original["conditions"]
    if conditions["judge"]["protocol"] != "judge-v2" or original.get("operational_error"):
        raise ValueError("completed judge-v2 report required")
    if digest(dataset.model_dump(mode="json")) != conditions["dataset_sha256"]:
        raise ValueError("dataset hash mismatch")
    if original.get("overrides_sha256") != digest({}):
        raise ValueError("overridden inputs cannot be replayed by this tool")
    kinds_path = kinds_path or dataset_path.resolve().parent / "judge-gold-kinds.json"
    kinds = read_json(kinds_path) if kinds_path.exists() else {}
    if digest(kinds) != conditions["judge"]["gold_kinds_sha256"]:
        raise ValueError("gold annotations hash mismatch")
    judge = Judge(gold_kinds=kinds)
    cases = {case.case_id: case for case in dataset.cases}
    rows = []
    seen = set()
    for row in original["results"]:
        case = cases[row["case_id"]]
        if (not case.oracle.semantic or row["status"] not in {"passed", "failed"}
                or row["error_type"] or row["key"] in seen):
            raise ValueError("unique completed semantic judgments required")
        seen.add(row["key"])
        completed = row["judge_diagnostics"][-1]
        if completed["stage"] != "complete" or completed["code"] != "ok":
            raise ValueError("successful final judge attempt required")
        name = f"{digest(row['key'])[:24]}-{completed['attempt']}.json"
        debug_path = report_path.parent / ".judge-debug" / name
        debug = read_json(debug_path)
        payload = debug["payload"]
        if digest(payload) != debug["payload_sha256"]:
            raise ValueError("debug payload changed, redacted, or truncated")
        if payload.get("images_sha256"):
            raise ValueError("image judgments require separate visual review")
        observation = Observation(scope="archived_judge_payload", answer=payload["answer"],
                                  evidence=payload["evidence"], data={"history": payload["history"]})
        expected = judge.build_payload(case, observation)
        for field in ("gold_document_titles", "fact_scope", "fact_answers", "last_answer"):
            expected.pop(field)
        if expected != payload:
            raise ValueError("payload does not match frozen case and annotations")
        verdict = judge._parse(debug["raw_verdict"])
        metrics = judge.score_verdict(verdict, payload, legacy_coverage=True)
        # Bind archived raw scores to the report; do not silently replay a different verdict.
        for metric, value in metrics.items():
            if metric.endswith("_raw"):
                name = metric.removesuffix("_raw")
            elif metric in {"fact_accuracy", "fact_contradiction_rate", "fact_unverifiable_rate",
                            "source_alias_correction_count", "claim_count"}:
                continue
            else:
                name = metric
            if name not in row["metrics"] or row["metrics"][name] != value:
                raise ValueError("archived verdict metrics do not match original report")
        limits = {name: limit for name, limit in case.oracle.limits.items() if name in metrics}
        if not limits:
            raise ValueError("no applicable semantic limits")
        failures = [name for name, limit in limits.items() if metrics[name] is None
                    or (limit.minimum is not None and metrics[name] < limit.minimum)
                    or (limit.maximum is not None and metrics[name] > limit.maximum)]
        rows.append({"key": row["key"], "original_status": row["status"],
                     "original_failures": row["failures"], "original_metrics": row["metrics"],
                     "debug_file": name, "debug_sha256": hashlib.sha256(debug_path.read_bytes()).hexdigest(),
                     "payload_sha256": debug["payload_sha256"], "semantic_metrics": metrics,
                     "semantic_limit_failures": failures, "semantic_limits_passed": not failures})
    if not rows:
        raise ValueError("no archived judgments")
    return {
        "protocol": "judge-source-regrade-v1", "kind": "retrospective_semantic_regrade",
        "created_at": datetime.now(UTC).isoformat(), "new_provider_requests": 0,
        "new_api_requests": 0, "original_report": str(report_path.resolve()),
        "original_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "original_conditions": conditions, "dataset_sha256": conditions["dataset_sha256"],
        "scorer_identity": {"protocol": "legacy-v2-source-only", "source_alias_rule": judge.identity["source_alias_rule"],
                            "coverage_bindings_validated": False}, "total": len(rows),
        "semantic_limits_passed": sum(row["semantic_limits_passed"] for row in rows), "cases": rows,
        "limitations": ["Archived answers and verdicts only; not a new API or provider run.",
                        "No full Observation capture; non-semantic checks and latency were not rerun.",
                        "Gold document identity is not evidence of actual context injection.",
                        "Legacy coverage is preserved, not validated or upgraded to judge-v6.",
                        "Not eligible as a normal evaluation baseline."],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline, auditable judge-v2 source-label regrade")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--gold-kinds", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New, non-existing directory")
    args = parser.parse_args(argv)
    try:
        result = regrade_report(args.report, args.dataset, args.gold_kinds)
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        path = args.output / "regrade.json"
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        print(json.dumps({"replay_completed": True, "semantic_limits_passed": result["semantic_limits_passed"],
                          "total": result["total"], "new_provider_requests": 0, "report": str(path)}))
        return 0 if result["semantic_limits_passed"] == result["total"] else 1
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print(json.dumps({"replay_completed": False, "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
