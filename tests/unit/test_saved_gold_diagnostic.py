from __future__ import annotations

import json

import pytest

from aiagent.evaluation.contracts import digest
from aiagent.evaluation.semantic import Judge, JudgeError
from scripts import diagnose_saved_gold as diagnostic
from scripts.build_adjudicated_regression import sha, write_new
from tests.unit.test_evaluation_judge_protocol import response


@pytest.fixture
def campaign(tmp_path):
    root = tmp_path / "campaign"
    (root / ".review").mkdir(parents=True)
    rows = []
    for index, case_id in enumerate(diagnostic.CASE_IDS):
        debug = root / str(index) / ".judge-debug"
        debug.mkdir(parents=True)
        key = case_id + "@1"
        payload = {"answer": "An apple is on the table.", "gold": {"object": "Fruit is on the table."},
                   "evidence": {}, "history": [], "persona": {}, "images_sha256": ["image-fixture"],
                   "allowed_fact_ids": ["object"], "allowed_behavior_ids": []}
        stored = {"payload": payload, "payload_sha256": digest(payload),
                  "stored_payload_sha256": digest(payload), "payload_transformed": False}
        input_path = debug / (digest(key)[:24] + "-input.json")
        write_new(input_path, stored)
        gold_payload = dict(payload, images_sha256=[], claim_quotes=[payload["answer"]])
        old = {"claims": [{"quote": payload["answer"], "truth": "unverifiable", "support": "insufficient"}],
               "covered_gold_ids": [], "coverage_claims": {}, "behavior_checks": {},
               "persona_violation": False, "style_score": 1,
               "coverage_assessments": {"object": {"gold_text": payload["gold"]["object"],
                                                    "relation": "entailed", "claim_quotes": [payload["answer"]]}}}
        write_new(debug / (digest(key + ":gold")[:24] + "-1.json"),
                  {"payload": gold_payload, "payload_sha256": digest(gold_payload), "raw_verdict": json.dumps(old)})
        report_path = root / str(index) / "report.json"
        write_new(report_path, {"results": [{"key": key, "case_id": case_id, "status": "judge_error",
                                            "error_code": "coverage_assessment_bindings_mismatch",
                                            "observation_sha256": digest(case_id)}]})
        rows.append({"case_id": case_id, "key": key, "answer": payload["answer"], "gold": payload["gold"],
                     "source_report": str(report_path.relative_to(root)), "source_report_sha256": sha(report_path),
                     "source_input": str(input_path), "source_input_sha256": sha(input_path),
                     "observation_sha256": digest(case_id)})
    write_new(root / ".review/pending-review.json", {"human_accepted": False, "baseline_eligible": False, "rows": rows})
    return root


def test_prepare_verifies_exact_saved_inputs_without_network(campaign):
    rows = diagnostic.prepare(campaign)
    assert tuple(row["case_id"] for row in rows) == diagnostic.CASE_IDS
    assert len(rows) == 4
    assert all(not row["payload"]["images_sha256"] for row in rows)
    assert all(row["source"]["payload_sha256"] == digest(row["payload"]) for row in rows)


@pytest.mark.parametrize("mutation", ["report_hash", "input_transform", "escape", "duplicate", "answer"])
def test_prepare_rejects_changed_or_out_of_scope_material(campaign, mutation):
    path = campaign / ".review/pending-review.json"
    packet = json.loads(path.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    if mutation == "report_hash":
        row["source_report_sha256"] = "wrong"
    elif mutation == "input_transform":
        source = diagnostic.inside(campaign, row["source_input"])
        value = json.loads(source.read_text(encoding="utf-8"))
        value["payload_transformed"] = True
        source.write_text(json.dumps(value), encoding="utf-8")
        row["source_input_sha256"] = sha(source)
    elif mutation == "escape":
        row["source_report"] = "../outside.json"
    elif mutation == "duplicate":
        packet["rows"].append(dict(row))
    else:
        row["answer"] = "A changed answer."
    path.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(ValueError):
        diagnostic.prepare(campaign)


def new_judge(monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "fixture")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "fixture-key")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "https://api.deepseek.com")
    return Judge("provider", max_repairs=0, request_budget=4, verify_visual_gold=True,
                 derive_gold_bindings=True, thinking_mode="disabled", max_output_tokens=8192)


def test_run_is_exactly_four_gold_only_requests_and_not_quality_acceptance(campaign, tmp_path, monkeypatch):
    rows = diagnostic.prepare(campaign)
    judge = new_judge(monkeypatch)
    calls = []

    def request(messages):
        calls.append(messages)
        payload = json.loads(messages[1]["content"][0]["text"])
        assert len(messages[1]["content"]) == 1 and not payload["images_sha256"]
        assert messages[0]["content"] == diagnostic.GOLD_DECISIONS_PROMPT
        assert "raw_verdict" not in payload
        return response({"claims": [{"quote": quote, "truth": "unverifiable"} for quote in payload["claim_quotes"]],
                         "coverage_assessments": {"object": {"gold_text": payload["gold"]["object"],
                                                             "relation": "entailed", "claim_quotes": payload["claim_quotes"]}}})

    monkeypatch.setattr(judge, "_request", request)
    output = tmp_path / "report"
    output.mkdir()
    report = diagnostic.diagnose(rows, judge, output)
    assert len(calls) == report["usage"]["logical_requests"] == 4
    assert report["usage"]["repair_requests"] == 0 and report["summary"] == {"valid": 4}
    assert report["quality_pass_rate"] is None and report["semantic_judge_calibrated"] is False
    assert report["baseline_eligible"] is False and report["human_accepted"] is False
    assert report["sut_requests"] == report["image_requests"] == 0
    assert all(row["truth_decisions_changed"] == 0 for row in report["results"])


def test_request_failure_stops_without_retry_or_spending_remaining_budget(campaign, tmp_path, monkeypatch):
    judge = new_judge(monkeypatch)
    calls = []

    def fail(messages):
        calls.append(messages)
        raise JudgeError("request", "request_timeout")

    monkeypatch.setattr(judge, "_request", fail)
    output = tmp_path / "report"
    output.mkdir()
    report = diagnostic.diagnose(diagnostic.prepare(campaign), judge, output)
    assert len(calls) == report["usage"]["logical_requests"] == 1
    assert report["summary"] == {"judge_error": 1, "not_run": 3}


def test_dry_run_does_not_construct_provider(campaign, monkeypatch):
    rows = diagnostic.prepare(campaign)
    monkeypatch.setattr(diagnostic, "prepare", lambda _: rows)
    monkeypatch.setattr(diagnostic, "Judge", lambda *a, **k: pytest.fail("provider constructed during dry run"))
    assert diagnostic.main([]) == 0
    with pytest.raises(SystemExit) as exc:
        diagnostic.main(["--execute", "--allow-provider"])
    assert exc.value.code == 2
