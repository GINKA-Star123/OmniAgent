"""Explicit, bounded gold-only diagnosis of four saved regression answers."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from aiagent.evaluation.contracts import digest, read_json
from aiagent.evaluation.semantic import GOLD_DECISIONS_PROMPT, Judge, JudgeError
from scripts.build_adjudicated_regression import ROOT, inside, sha, write_new

CASE_IDS = (
    "vision-d02825d4d14e-wrong-hint", "vision-4b8819e05393-wrong-hint",
    "vision-d91513554e01-normal", "vision-d91513554e01-wrong-hint",
)
DEFAULT_CAMPAIGN = ROOT / "data/cache/reports/vision-candidate-diagnostic-20261101T072006Z"


def prepare(campaign: Path) -> list[dict]:
    campaign = campaign.resolve()
    packet_path = inside(campaign, ".review/pending-review.json")
    packet = read_json(packet_path)
    if packet.get("human_accepted") is not False or packet.get("baseline_eligible") is not False:
        raise ValueError("saved_review_scope_invalid")
    selected = [row for row in packet["rows"] if row["case_id"] in CASE_IDS]
    if Counter(row["case_id"] for row in selected) != Counter(CASE_IDS):
        raise ValueError("saved_case_selection_invalid")
    rows = []
    for case_id in CASE_IDS:
        row = next(item for item in selected if item["case_id"] == case_id)
        report_path = inside(campaign, row["source_report"])
        input_path = inside(campaign, row["source_input"])
        if sha(report_path) != row["source_report_sha256"] or sha(input_path) != row["source_input_sha256"]:
            raise ValueError("saved_source_hash_mismatch")
        source = read_json(report_path)
        matches = [item for item in source["results"] if item["key"] == row["key"]]
        if (len(matches) != 1 or matches[0]["case_id"] != case_id
                or matches[0]["status"] != "judge_error"
                or matches[0]["error_code"] != "coverage_assessment_bindings_mismatch"
                or matches[0]["observation_sha256"] != row["observation_sha256"]):
            raise ValueError("saved_failure_identity_mismatch")
        stored = read_json(input_path)
        payload = stored["payload"]
        if (stored.get("payload_transformed") is not False
                or digest(payload) != stored["payload_sha256"]
                or digest(payload) != stored["stored_payload_sha256"]
                or payload["answer"] != row["answer"] or payload["gold"] != row["gold"]):
            raise ValueError("saved_payload_transformed")
        gold_path = inside(campaign, str(input_path.parent / (digest(row["key"] + ":gold")[:24] + "-1.json")))
        gold_saved = read_json(gold_path)
        gold_payload = gold_saved["payload"]
        old = Judge._parse(gold_saved["raw_verdict"])
        quotes = [claim.quote for claim in old.claims]
        expected = dict(payload, images_sha256=[], evidence={}, history=[], persona={}, claim_quotes=quotes)
        if (digest(gold_payload) != gold_saved["payload_sha256"] or gold_payload != expected
                or not quotes or len(quotes) != len(set(quotes))
                or gold_payload["allowed_behavior_ids"] or not gold_payload["allowed_fact_ids"]):
            raise ValueError("saved_gold_payload_mismatch")
        Judge._validate_channel(old, "gold", quotes)
        try:
            Judge.validate(old, gold_payload, independent_coverage=True)
        except JudgeError as exc:
            if exc.code != "coverage_assessment_bindings_mismatch":
                raise ValueError("saved_gold_failure_changed") from exc
        else:
            raise ValueError("saved_gold_failure_missing")
        rows.append({"case_id": case_id, "key": row["key"], "payload": gold_payload, "old": old,
                     "source": {"report": row["source_report"], "report_sha256": sha(report_path),
                                "input_sha256": sha(input_path), "gold_artifact_sha256": sha(gold_path),
                                "payload_sha256": digest(gold_payload), "review_packet_sha256": sha(packet_path)}})
    return rows


def diagnose(rows: list[dict], judge: Judge, output: Path) -> dict:
    if (tuple(row["case_id"] for row in rows) != CASE_IDS or judge.mode != "provider"
            or not judge.derive_gold_bindings or judge.max_repairs != 0
            or judge.request_budget != 4 or judge.usage["logical_requests"] != 0):
        raise ValueError("fixed_gold_diagnostic_scope_invalid")
    report = {"protocol": "fixed-saved-gold-diagnostic-v1", "baseline_eligible": False,
              "human_accepted": False, "semantic_judge_calibrated": False, "heldout_touched": False,
              "sut_requests": 0, "image_requests": 0, "automatic_replay_allowed": False,
              "explicit_private_replay_authorized": True, "fixed_answers_not_sut_generated": True,
              "judge": judge.identity, "runner_source_sha256": sha(Path(__file__)),
              "sources": {row["case_id"]: row["source"] for row in rows}, "results": []}
    write_new(output / "plan.json", report)
    stop = False
    for row in rows:
        judge.diagnostics = []
        result = {"case_id": row["case_id"], "protocol_status": "not_run"}
        if stop:
            result["error_code"] = "stopped_after_request_or_internal_error"
        else:
            try:
                key = row["key"] + ":compact-gold-diagnostic"
                if judge.debug is not None:
                    judge.debug.write_input(key, row["payload"])
                verdict = judge._provider_verdict(key, row["payload"], [], prompt=GOLD_DECISIONS_PROMPT,
                                                  channel="gold", expected_quotes=row["payload"]["claim_quotes"])
                old = row["old"]
                old_truths = {claim.quote: claim.truth for claim in old.claims}
                result.update(protocol_status="valid", claim_truth_counts=dict(Counter(c.truth for c in verdict.claims)),
                              truth_decisions_changed=sum(c.truth != old_truths[c.quote] for c in verdict.claims),
                              covered_gold_ids=verdict.covered_gold_ids,
                              relations={key: value.relation for key, value in verdict.coverage_assessments.items()},
                              relation_changes={key: {"old": old.coverage_assessments[key].relation, "new": value.relation}
                                                for key, value in verdict.coverage_assessments.items()
                                                if value.relation != old.coverage_assessments[key].relation})
            except JudgeError as exc:
                result.update(protocol_status="judge_error", error_code=exc.code, error_stage=exc.stage)
                stop = exc.stage in {"request", "budget", "internal"}
            except Exception as exc:
                result.update(protocol_status="judge_error", error_code="diagnostic_internal_error",
                              error_stage="internal", error_type=type(exc).__name__)
                stop = True
        result["diagnostics"] = [item.model_dump(mode="json") for item in judge.diagnostics]
        report["results"].append(result)
        write_new(output / (row["case_id"] + ".json"), result)
    report["summary"] = dict(Counter(row["protocol_status"] for row in report["results"]))
    report["usage"] = dict(judge.usage)
    report["quality_pass_rate"] = None
    write_new(output / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--output", type=Path, default=ROOT / "data/cache/reports/fixed-saved-gold-diagnostic")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-provider", action="store_true")
    parser.add_argument("--acknowledge-private-replay", action="store_true")
    args = parser.parse_args(argv)
    rows = prepare(args.campaign)
    if not args.execute:
        print(json.dumps({"execute": False, "case_ids": list(CASE_IDS), "network": False,
                          "payloads_sha256": digest([row["payload"] for row in rows])}))
        return 0
    if not args.allow_provider or not args.acknowledge_private_replay:
        parser.error("execution requires provider permission and explicit private replay acknowledgement")
    output = args.output.resolve() / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    judge = Judge("provider", max_repairs=0, request_budget=4, max_output_tokens=8192, thinking_mode="disabled",
                  verify_visual_gold=True, derive_gold_bindings=True, debug_directory=output / ".judge-debug")
    report = diagnose(rows, judge, output)
    code = 0 if report["summary"] == {"valid": 4} else 2
    print(json.dumps({"exit_code": code, "report": str(output / "report.json"),
                      "summary": report["summary"], "usage": report["usage"]}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
