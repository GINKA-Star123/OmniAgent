from __future__ import annotations

import json
from copy import deepcopy

import pytest

from aiagent.evaluation.contracts import read_json
from aiagent.evaluation.semantic import GOLD_REVIEW_PROMPT, JudgeError
from scripts import calibrate_evaluation_judge as calibration
from tests.unit.test_evaluation_judge_protocol import provider, response


def references():
    return {"version": "judge-adjudication-calibration-v1", "status": "agent_labeled",
            "cases": [{"id": "fruit-extra", "answer": "桌上有一盘苹果。", "gold": "桌上有水果。",
                       "relation": "entailed", "truth": "unverifiable"}]}


def test_derived_policy_uses_runtime_compact_prompt_without_expected_labels(monkeypatch, tmp_path):
    ref = references()
    data = verdict(ref["cases"][0])
    raw = {"claims": [{"quote": c["quote"], "truth": c["truth"]} for c in data["claims"]],
           "coverage_assessments": data["coverage_assessments"]}
    judge, calls = provider(monkeypatch, [response(raw)], max_repairs=0, request_budget=1,
                            verify_visual_gold=True, derive_gold_bindings=True)
    report = calibration.calibrate(ref, judge, tmp_path, gold_policy="derived")
    assert report["all_references_matched"] and len(calls) == 1
    assert calls[0][0]["content"] == calibration.GOLD_DECISIONS_PROMPT
    payload = json.loads(calls[0][1]["content"][0]["text"])
    assert not {"expected_relation", "expected_truth", "relation", "truth"} & payload.keys()
    assert report["baseline_eligible"] is False and report["human_accepted"] is False


def test_derived_policy_rejects_legacy_judge_before_requests(monkeypatch, tmp_path):
    judge, calls = provider(monkeypatch, [], max_repairs=0, request_budget=1)
    with pytest.raises(ValueError, match="紧凑gold协议"):
        calibration.calibrate(references(), judge, tmp_path, gold_policy="derived")
    assert not calls


def test_open_world_policy_is_opt_in_and_does_not_leak_reference_labels(monkeypatch, tmp_path):
    from aiagent.evaluation.semantic import GOLD_DECISIONS_PROMPT, Judge

    ref = references()
    data = verdict(ref["cases"][0])
    raw = {"claims": [{"quote": claim["quote"], "truth": claim["truth"]} for claim in data["claims"]],
           "coverage_assessments": data["coverage_assessments"]}
    judge, calls = provider(monkeypatch, [response(raw)], max_repairs=0, request_budget=1,
                            verify_visual_gold=True, derive_gold_bindings=True)
    before = Judge().identity
    report = calibration.calibrate(ref, judge, tmp_path, gold_policy="derived-open-world")
    assert report["all_references_matched"] and len(calls) == 1
    assert calls[0][0]["content"] == calibration.OPEN_WORLD_GOLD_PROMPT
    assert calibration.OPEN_WORLD_GOLD_PROMPT.startswith(GOLD_DECISIONS_PROMPT)
    assert "明确否定和排他约束必须尊重" in calibration.OPEN_WORLD_GOLD_PROMPT
    assert Judge().identity == before
    payload = json.loads(calls[0][1]["content"][0]["text"])
    assert not {"relation", "truth", "expected_relation", "expected_truth"} & payload.keys()
    assert report["experimental_prompt_not_runtime_default"] is True


def test_position_references_keep_unknown_and_explicit_contradiction_distinct():
    path = calibration.CALIBRATION.with_name("judge-readiness-position-20261102.json")
    refs = calibration.load_references(path)
    assert len(refs["cases"]) == 4
    assert [(row["relation"], row["truth"]) for row in refs["cases"]] == [
        ("partial", "unverifiable"), ("partial", "unverifiable"),
        ("contradicted", "incorrect"), ("contradicted", "incorrect")]
    assert "not_human_accepted" in refs["status"]


def verdict(row, relation="entailed", truth="unverifiable"):
    covered = relation == "entailed"
    return {"claims": [{"quote": row["answer"], "support": "insufficient", "truth": truth,
                        "evidence_quotes": {}, "citation_ids": [], "visual_support": "not_applicable"}],
            "covered_gold_ids": ["target"] if covered else [],
            "coverage_claims": {"target": [row["answer"]]} if covered else {},
            "coverage_assessments": {"target": {"gold_text": row["gold"], "relation": relation,
                "claim_quotes": [] if relation == "not_addressed" else [row["answer"]]}},
            "behavior_checks": {}, "persona_violation": False, "style_score": 1}


def test_reference_expectations_never_enter_judge_payload(monkeypatch, tmp_path):
    ref = references()
    ref["cases"][0].update(valid_quote="桌上有一盘苹果", invalid_quote="不存在的引用")
    judge, calls = provider(monkeypatch, [response(verdict(ref["cases"][0]))], max_repairs=0, request_budget=1)
    before = deepcopy(ref)
    result = calibration.calibrate(ref, judge, tmp_path)
    assert result["summary"]["passed"] == 1
    assert result["baseline_eligible"] is result["human_accepted"] is False
    assert result["heldout_touched"] is result["sut_called"] is False
    assert result["usage"]["logical_requests"] == 1
    assert calls[0][0]["content"] == GOLD_REVIEW_PROMPT
    payload = json.loads(calls[0][1]["content"][0]["text"])
    assert payload["claim_quotes"] == [ref["cases"][0]["answer"]]
    assert payload["evidence"] == {} and payload["images_sha256"] == []
    assert not {"relation", "truth", "valid_quote", "invalid_quote", "expected_relation"} & payload.keys()
    assert ref == before
    assert read_json(tmp_path / "report.json") == result


def test_extra_detail_truth_and_coverage_are_independent(monkeypatch, tmp_path):
    ref = references()
    judge, _ = provider(monkeypatch, [response(verdict(ref["cases"][0], truth="correct"))],
                        max_repairs=0, request_budget=1)
    report = calibration.calibrate(ref, judge, tmp_path)
    assert report["summary"]["relation_matches"] == 1
    assert report["summary"]["truth_matches"] == 0
    assert report["summary"]["false_truth_count"] == 1
    assert not report["all_references_matched"]


@pytest.mark.parametrize("failure", ["quote", "timeout", "wrong_relation"])
def test_errors_and_false_coverage_stay_in_denominator_without_retries(monkeypatch, tmp_path, failure):
    ref = references()
    ref["cases"][0].update(relation="partial")
    data = verdict(ref["cases"][0])
    if failure == "quote":
        data["claims"][0]["quote"] = "不存在的引用"
        data["coverage_claims"]["target"] = ["不存在的引用"]
        data["coverage_assessments"]["target"]["claim_quotes"] = ["不存在的引用"]
    reply = JudgeError("request", "request_timeout") if failure == "timeout" else response(data)
    judge, calls = provider(monkeypatch, [reply], max_repairs=0, request_budget=1)
    report = calibration.calibrate(ref, judge, tmp_path)
    assert report["summary"]["total"] == 1 and report["summary"]["pass_rate"] == 0
    assert report["summary"]["false_coverage_count"] == int(failure == "wrong_relation")
    assert report["summary"]["judge_errors"] == int(failure != "wrong_relation")
    assert len(calls) == 1 and report["usage"]["repair_requests"] == 0


def test_no_provider_without_explicit_execute_and_consent(monkeypatch, tmp_path, capsys):
    path = tmp_path / "references.json"
    path.write_text(json.dumps(references()), encoding="utf-8")
    def forbidden(*args, **kwargs):
        pytest.fail("不允许请求模型")
    monkeypatch.setattr(calibration.Judge, "_request", forbidden)
    assert calibration.main(["--references", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["network"] is False
    with pytest.raises(SystemExit):
        calibration.main(["--references", str(path), "--execute"])
    assert not (tmp_path / "report.json").exists()


def test_request_failure_stops_later_calls_but_preserves_denominator(monkeypatch, tmp_path):
    ref = references()
    ref["cases"].append(dict(ref["cases"][0], id="second-reference"))
    judge, calls = provider(monkeypatch, [JudgeError("request", "request_authentication_failed")],
                            max_repairs=0, request_budget=2)
    report = calibration.calibrate(ref, judge, tmp_path)
    assert len(calls) == 1
    assert report["summary"]["total"] == 2
    assert report["summary"]["judge_errors"] == report["summary"]["not_run"] == 1
    assert report["summary"]["pass_rate"] == 0


def test_refuse_repairs_or_wrong_budget_before_any_request(monkeypatch, tmp_path):
    judge, calls = provider(monkeypatch, [], max_repairs=1, request_budget=1)
    with pytest.raises(ValueError, match="max_repairs"):
        calibration.calibrate(references(), judge, tmp_path)
    judge.max_repairs = 0
    judge.request_budget = 2
    with pytest.raises(ValueError, match="硬预算"):
        calibration.calibrate(references(), judge, tmp_path)
    assert not calls and not list(tmp_path.iterdir())


def test_report_creation_refuses_overwrite_before_request(monkeypatch, tmp_path):
    judge, calls = provider(monkeypatch, [], max_repairs=0, request_budget=1)
    (tmp_path / "plan.json").write_text("old report", encoding="utf-8")
    with pytest.raises(FileExistsError):
        calibration.calibrate(references(), judge, tmp_path)
    assert not calls


def test_actual_references_are_valid_and_negation_is_contiguous():
    ref = calibration.load_references(calibration.CALIBRATION)
    assert len(ref["cases"]) == 24
    row = next(row for row in ref["cases"] if row["id"] == "quote-negation-full")
    payload = calibration.reference_payload(row)
    assert payload["claim_quotes"] == [row["answer"]]
    assert row["invalid_quote"] not in row["answer"]


def test_experimental_prompt_is_opt_in_and_never_changes_runtime(monkeypatch, tmp_path):
    from aiagent.evaluation.contracts import digest
    from aiagent.evaluation.semantic import Judge

    ref = references()
    judge, calls = provider(monkeypatch, [response(verdict(ref["cases"][0]))], max_repairs=0, request_budget=1)
    report = calibration.calibrate(ref, judge, tmp_path, gold_policy="compact")
    assert calls[0][0]["content"] == calibration.COMPACT_GOLD_PROMPT
    assert report["actual_gold_prompt_sha256"] == digest(calibration.COMPACT_GOLD_PROMPT)
    assert report["experimental_prompt_not_runtime_default"] is True
    assert Judge().identity["protocol"] == "judge-v8"
    assert "两个方向" in calibration.COMPACT_GOLD_PROMPT


def test_unknown_selection_fails_without_network(monkeypatch, tmp_path):
    path = tmp_path / "references.json"
    path.write_text(json.dumps(references()), encoding="utf-8")
    with pytest.raises(SystemExit):
        calibration.main(["--references", str(path), "--case-id", "does-not-exist"])


@pytest.mark.parametrize("reverse_relation,expected", [("partial", "unverifiable"),
    ("entailed", "correct"), ("contradicted", "incorrect"), ("not_addressed", "unverifiable")])
def test_bidirectional_judgments_do_not_see_each_other(monkeypatch, tmp_path, reverse_relation, expected):
    ref = references()
    row = ref["cases"][0]
    reverse_row = dict(row, answer=row["gold"], gold=row["answer"])
    judge, calls = provider(monkeypatch, [response(verdict(row)),
        response(verdict(reverse_row, relation=reverse_relation))], max_repairs=0, request_budget=2)
    report = calibration.calibrate(ref, judge, tmp_path, gold_policy="bidirectional")
    forward = json.loads(calls[0][1]["content"][0]["text"])
    backward = json.loads(calls[1][1]["content"][0]["text"])
    assert forward["answer"] == backward["gold"]["target"] == row["answer"]
    assert backward["answer"] == forward["gold"]["target"] == row["gold"]
    assert all(call[0]["content"] == calibration.NLI_REVIEW_PROMPT for call in calls)
    assert "observed_relation" not in backward and "truth" not in backward
    assert report["results"][0]["observed_truth"] == expected
    assert report["usage"]["logical_requests"] == 2
    assert len(report["results"][0]["diagnostics"]) == 2
    if reverse_relation == "contradicted":
        assert report["results"][0]["status"] == "judge_error"
        assert report["results"][0]["error_code"] == "contradiction_direction_mismatch"
        assert report["summary"]["direction_inconsistency_count"] == 1


def test_calibration_rejects_reused_judge_before_network(monkeypatch, tmp_path):
    judge, calls = provider(monkeypatch, [], max_repairs=0, request_budget=1)
    judge.usage["logical_requests"] = 1
    with pytest.raises(ValueError, match="新 Judge"):
        calibration.calibrate(references(), judge, tmp_path)
    assert not calls


def test_boundary_policy_remains_opt_in_and_uses_two_separate_requests(monkeypatch, tmp_path):
    ref = references()
    row = ref["cases"][0]
    reverse = dict(row, answer=row["gold"], gold=row["answer"])
    judge, calls = provider(monkeypatch, [response(verdict(row)), response(verdict(reverse, relation="partial"))],
                            max_repairs=0, request_budget=2)
    report = calibration.calibrate(ref, judge, tmp_path, gold_policy="bidirectional-v2")
    assert all(call[0]["content"] == calibration.NLI_REVIEW_PROMPT_V2 for call in calls)
    assert report["summary"]["passed"] == 1
    assert report["requests_per_case"] == 2
    assert report["experimental_prompt_not_runtime_default"] is True


def test_new_contrasts_are_separate_from_original_references():
    path = calibration.CALIBRATION.with_name("judge-boundary-calibration-20261101.json")
    contrasts = calibration.load_references(path)
    originals = calibration.load_references(calibration.CALIBRATION)
    assert len(contrasts["cases"]) == 16
    assert {row["id"] for row in contrasts["cases"]}.isdisjoint(row["id"] for row in originals["cases"])
    assert "not_human_accepted" in contrasts["status"]
    for row in contrasts["cases"]:
        assert calibration.reference_payload(row)["claim_quotes"] == [row["answer"]]
