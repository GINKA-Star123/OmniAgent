from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy

import pytest

from aiagent.evaluation.contracts import digest
from aiagent.evaluation.reporting import compare_reports
from aiagent.evaluation.scoring import score
from aiagent.evaluation.semantic import Judge
from tests.unit.test_evaluation_contracts import semantic_case
from tests.unit.test_evaluation_judge_protocol import observation, provider, response, verdict
from tests.unit.test_evaluation_targeted_repairs import visual_fixture


def test_only_binding_repair_keeps_first_decisions_and_can_pass(monkeypatch):
    first = verdict()
    first["coverage_claims"] = {}
    judge, calls = provider(monkeypatch, [response(first), response(verdict())], request_budget=2)
    result = score(semantic_case(), observation(), judge, "repair@1")
    assert result.status == "passed" and len(calls) == 2
    assert [item.code for item in result.judge_diagnostics] == ["coverage_bindings_mismatch", "ok"]
    assert judge.usage["logical_requests"] == 2 and judge.usage["repair_requests"] == 1


@pytest.mark.parametrize("change", ["truth", "support", "visual", "coverage", "claims", "persona", "style"])
def test_structural_retry_cannot_change_any_quality_decision(monkeypatch, change):
    first = verdict()
    first["coverage_claims"] = {}
    repaired = verdict()
    if change == "truth":
        repaired["claims"][0]["truth"] = "unverifiable"
        repaired.update(covered_gold_ids=[], coverage_claims={})
    elif change == "support":
        repaired["claims"][0].update(support="insufficient", evidence_quotes={})
    elif change == "visual":
        repaired["claims"][0]["visual_support"] = "visible"
    elif change == "coverage":
        repaired.update(covered_gold_ids=[], coverage_claims={})
    elif change == "claims":
        repaired["claims"] = []
        repaired.update(covered_gold_ids=[], coverage_claims={})
    elif change == "persona":
        repaired["persona_violation"] = True
    else:
        repaired["style_score"] = 0.9
    judge, calls = provider(monkeypatch, [response(first), response(repaired)], request_budget=2)
    result = score(semantic_case(), observation(), judge, "repair@1")
    assert result.status == "judge_error" and result.error_code == "repair_semantics_changed"
    assert result.metrics == {} and len(calls) == 2
    assert not result.judge_diagnostics[-1].retryable
    assert "星蓝" not in result.model_dump_json()


def test_behavior_upgrade_is_not_a_format_repair(monkeypatch):
    case = semantic_case()
    case.oracle.gold["care"] = "停止伤人的玩笑。"
    first = verdict()
    first.update(coverage_claims={}, behavior_checks={"care": "violated"})
    repaired = deepcopy(first)
    repaired.update(coverage_claims={"color": ["星蓝"]}, behavior_checks={"care": "satisfied"})
    judge, calls = provider(monkeypatch, [response(first), response(repaired)],
                            request_budget=2, gold_kinds={case.case_id: {"care": "behavior"}})
    result = score(case, observation(), judge, "repair@1")
    assert result.error_code == "repair_semantics_changed" and len(calls) == 2


@pytest.mark.parametrize("raw", ["broken JSON", {}, {"claims": []}])
def test_no_parseable_initial_decision_means_no_paid_retry(monkeypatch, raw):
    judge, calls = provider(monkeypatch, [response(raw), response(verdict())], request_budget=2)
    result = score(semantic_case(), observation(), judge, "repair@1")
    assert result.status == "judge_error" and result.error_stage == "parse"
    assert len(calls) == 1 and judge.usage["repair_requests"] == 0
    assert not result.judge_diagnostics[0].retryable


def test_truncated_output_cannot_become_a_new_quality_attempt(monkeypatch):
    judge, calls = provider(monkeypatch, [response(verdict(), "length"), response(verdict())], request_budget=2)
    result = score(semantic_case(), observation(), judge, "repair@1")
    assert result.error_code == "response_truncated" and len(calls) == 1
    assert not result.judge_diagnostics[0].retryable


def test_unknown_fact_ids_do_not_create_a_semantic_anchor(monkeypatch):
    first = verdict()
    first.update(covered_gold_ids=["invented"], coverage_claims={"invented": ["星蓝"]})
    judge, calls = provider(monkeypatch, [response(first), response(verdict())], request_budget=2)
    result = score(semantic_case(), observation(), judge, "repair@1")
    assert result.error_code == "gold_identifier_invalid" and len(calls) == 1


def test_missing_gold_claims_cannot_be_added_by_a_repair(tmp_path, monkeypatch):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    first = dict(gold, claims=[])
    judge, calls = provider(monkeypatch, [response(visual), response(first), response(gold)],
                            verify_visual_gold=True, request_budget=3)
    result = score(case, obs, judge, "repair@1")
    assert result.status == "judge_error" and len(calls) == 2
    assert judge.usage["repair_requests"] == 0


def test_gold_partial_must_not_upgrade_to_entailed_on_binding_repair(tmp_path, monkeypatch):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    gold["coverage_assessments"]["object"].update(relation="partial", claim_quotes=[obs.answer])
    first = deepcopy(gold)
    first.update(covered_gold_ids=["object"], coverage_claims={"object": [obs.answer]})
    upgraded = deepcopy(first)
    upgraded["coverage_assessments"]["object"]["relation"] = "entailed"
    judge, calls = provider(monkeypatch, [response(visual), response(first), response(upgraded)],
                            verify_visual_gold=True, request_budget=3)
    result = score(case, obs, judge, "repair@1")
    assert result.error_code == "repair_semantics_changed" and result.metrics == {}
    assert len(calls) == 3 and judge.usage["repair_requests"] == 1
    assert [item.channel for item in result.judge_diagnostics] == ["visual", "gold", "gold"]


def test_gold_binding_can_be_corrected_without_changing_partial(tmp_path, monkeypatch):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    gold["coverage_assessments"]["object"].update(relation="partial", claim_quotes=[obs.answer])
    first = deepcopy(gold)
    first.update(covered_gold_ids=["object"], coverage_claims={"object": [obs.answer]})
    judge, calls = provider(monkeypatch, [response(visual), response(first), response(gold)],
                            verify_visual_gold=True, request_budget=3)
    result = score(case, obs, judge, "repair@1")
    assert result.status == "failed" and result.metrics["gold_coverage"] == 0
    assert len(calls) == 3


def test_repair_anchor_is_local_and_not_replayed_as_model_instructions(monkeypatch):
    first = verdict()
    first["coverage_claims"] = {}
    judge, calls = provider(monkeypatch, [response(first), response(verdict())], request_budget=2)
    assert score(semantic_case(), observation(), judge, "repair@1").status == "passed"
    first_payload = json.loads(calls[0][1]["content"][0]["text"])
    second_payload = json.loads(calls[1][1]["content"][0]["text"])
    assert digest(first_payload) == digest(second_payload)
    assert not any(message["role"] == "assistant" for message in calls[1])
    assert "freeze-first-decisions-v1" not in json.dumps(calls[1])


def test_new_repair_condition_cannot_compare_as_old_baseline():
    current = {"protocol": "fixture", "conditions": {"judge": Judge().identity}}
    old = deepcopy(current)
    del old["conditions"]["judge"]["repair_policy"]
    with pytest.raises(ValueError):
        compare_reports(current, old)


def test_actual_judge_message_keeps_image_bytes_and_order(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    paths = [tmp_path / "one.jpg", tmp_path / "two.png"]
    images = []
    for index, path in enumerate(paths):
        binary = b"offline transport fixture: " + str(index).encode()
        path.write_bytes(binary)
        images.append({"path": str(path), "sha256": hashlib.sha256(binary).hexdigest()})
    case = semantic_case()
    obs = observation()
    obs.data["evaluation_images"] = images
    judge, calls = provider(monkeypatch, [response(verdict())], max_repairs=0)
    assert score(case, obs, judge, "transport@1").status == "passed"
    content = calls[0][1]["content"]
    assert json.loads(content[0]["text"])["images_sha256"] == [image["sha256"] for image in images]
    for item, path, mime in zip(content[1:], paths, ["image/jpeg", "image/png"], strict=True):
        header, encoded = item["image_url"]["url"].split(",", 1)
        assert header == "data:" + mime + ";base64"
        assert base64.b64decode(encoded, validate=True) == path.read_bytes()
