from __future__ import annotations

import json
from copy import deepcopy

import pytest

from aiagent.evaluation import cli
from aiagent.evaluation.contracts import digest
from aiagent.evaluation.scoring import score
from aiagent.evaluation.semantic import GOLD_DECISIONS_PROMPT, GoldDecisions, Judge, JudgeError
from tests.unit.test_evaluation_judge_protocol import provider, response
from tests.unit.test_evaluation_targeted_repairs import visual_fixture


def decisions(gold):
    return {"claims": [{"quote": c["quote"], "truth": c["truth"]} for c in gold["claims"]],
            "coverage_assessments": deepcopy(gold["coverage_assessments"])}


def test_compact_prompt_requires_entire_claim_not_only_matching_head_fact():
    assert "truth=correct 必须由 gold 证实整个 quote 的全部事实条件" in GOLD_DECISIONS_PROMPT
    assert "种类、颜色、材质、长度、数量、风格、动作和位置" in GOLD_DECISIONS_PROMPT
    assert "truth=unverifiable" in GOLD_DECISIONS_PROMPT
    assert "truth=correct，但该目标只能 partial" in GOLD_DECISIONS_PROMPT


def test_unverified_compound_claim_can_cover_broad_goal_without_truth_upgrade(monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "fixture")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "fixture-key")
    judge = Judge("provider", max_repairs=0, verify_visual_gold=True, derive_gold_bindings=True)
    payload = {"answer": "A blue plastic box is on the table.", "fact_answers": ["A blue plastic box is on the table."],
               "evidence": {}, "gold": {"object": "A box is on the table."},
               "allowed_fact_ids": ["object"], "allowed_behavior_ids": [], "images_sha256": []}
    raw = {"claims": [{"quote": payload["answer"], "truth": "unverifiable"}],
           "coverage_assessments": {"object": {"gold_text": payload["gold"]["object"],
                                                "relation": "entailed", "claim_quotes": [payload["answer"]]}}}
    verdict = GoldDecisions.model_validate(raw).to_verdict()
    judge.validate(verdict, payload, independent_coverage=True)
    metrics = judge.score_verdict(verdict, payload, independent_coverage=True)
    assert metrics["gold_coverage"] == 1 and metrics["fact_accuracy_raw"] == 0
    assert metrics["fact_unverifiable_rate_raw"] == 1


@pytest.mark.parametrize(("relation", "truth", "covered"), [
    ("entailed", "correct", True), ("entailed", "unverifiable", True),
    ("partial", "unverifiable", False), ("contradicted", "incorrect", False),
    ("not_addressed", "unverifiable", False),
])
def test_compact_decisions_preserve_quality_and_derive_only_structure(tmp_path, monkeypatch, relation, truth, covered):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    raw = decisions(gold)
    raw["claims"][0]["truth"] = truth
    raw["coverage_assessments"]["object"].update(relation=relation,
        claim_quotes=[] if relation == "not_addressed" else [obs.answer])
    before = deepcopy(raw)
    judge, calls = provider(monkeypatch, [response(visual), response(raw)], verify_visual_gold=True,
                            derive_gold_bindings=True, max_repairs=0, request_budget=2)
    result = score(case, obs, judge, "derive@1")
    assert result.status == ("passed" if covered else "failed")
    assert result.metrics["gold_coverage"] == int(covered)
    assert result.metrics["fact_accuracy"] == int(truth == "correct")
    assert raw == before and len(calls) == 2 and judge.usage["repair_requests"] == 0
    assert calls[1][0]["content"] == GOLD_DECISIONS_PROMPT
    assert len(calls[1][1]["content"]) == 1
    identity = judge.identity
    assert identity["gold_binding_rule"] == "derive-explicit-relations-v1"
    assert identity["gold_prompt_sha256"] == digest(GOLD_DECISIONS_PROMPT)


@pytest.mark.parametrize(("mutation", "code"), [
    ("incorrect_entailed", "coverage_claim_incorrect"),
    ("unknown_id", "coverage_assessments_mismatch"),
    ("missing_id", "coverage_assessments_mismatch"),
    ("wrong_gold", "coverage_gold_text_mismatch"),
    ("empty_binding", "coverage_claims_empty"),
    ("bad_quote", "claim_quote_not_in_answer"),
    ("drop_claim", "coverage_claim_missing"),
    ("binding_duplicate", "coverage_claim_duplicate"),
    ("unaddressed_bound", "coverage_unaddressed_has_claims"),
    ("extra_covered", "verdict_schema_invalid"),
    ("extra_support", "verdict_schema_invalid"),
])
def test_derived_mode_does_not_relax_semantic_or_schema_validation(tmp_path, monkeypatch, mutation, code):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    raw = decisions(gold)
    assessment = raw["coverage_assessments"]["object"]
    assessment.update(relation="entailed", claim_quotes=[obs.answer])
    if mutation == "incorrect_entailed":
        raw["claims"][0]["truth"] = "incorrect"
    elif mutation == "unknown_id":
        raw["coverage_assessments"]["unknown"] = raw["coverage_assessments"].pop("object")
    elif mutation == "missing_id":
        raw["coverage_assessments"] = {}
    elif mutation == "wrong_gold":
        assessment["gold_text"] = "not the original gold"
    elif mutation == "empty_binding":
        assessment["claim_quotes"] = []
    elif mutation == "bad_quote":
        raw["claims"][0]["quote"] = "invented quote"
        assessment["claim_quotes"] = ["invented quote"]
    elif mutation == "drop_claim":
        raw["claims"] = []
    elif mutation == "binding_duplicate":
        assessment["claim_quotes"] *= 2
    elif mutation == "unaddressed_bound":
        assessment["relation"] = "not_addressed"
    elif mutation == "extra_covered":
        raw["covered_gold_ids"] = ["object"]
    else:
        raw["claims"][0]["support"] = "supported"
    judge, calls = provider(monkeypatch, [response(visual), response(raw)], verify_visual_gold=True,
                            derive_gold_bindings=True, max_repairs=0, request_budget=2)
    result = score(case, obs, judge, "bad@1")
    assert result.status == "judge_error" and result.error_code == code
    assert len(calls) == 2 and judge.usage["repair_requests"] == 0 and result.metrics == {}


def test_old_contradictory_redundant_fields_are_still_rejected(tmp_path, monkeypatch):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    gold["coverage_assessments"]["object"].update(relation="entailed", claim_quotes=[obs.answer])
    judge, _ = provider(monkeypatch, [response(visual), response(gold)], verify_visual_gold=True, max_repairs=0)
    result = score(case, obs, judge, "legacy@1")
    assert result.error_code == "coverage_assessment_bindings_mismatch"
    assert judge.identity["gold_binding_rule"] == "model-asserted-v1"


@pytest.mark.parametrize("kwargs", [
    {"derive_gold_bindings": True},
    {"derive_gold_bindings": True, "verify_visual_gold": True},
])
def test_opt_in_requires_provider_split_and_no_repairs(kwargs):
    with pytest.raises(JudgeError) as error:
        Judge(**kwargs)
    assert error.value.stage == "configuration"


def test_compact_parser_rejects_duplicate_json_keys_and_does_not_mutate():
    with pytest.raises(JudgeError, match="verdict_json_invalid"):
        Judge._parse('{"claims":[],"claims":[],"coverage_assessments":{}}', gold_decisions=True)
    raw = {"claims": [], "coverage_assessments": {}}
    before = deepcopy(raw)
    value = GoldDecisions.model_validate(raw)
    assert value.to_verdict().covered_gold_ids == [] and raw == before


@pytest.mark.parametrize("release", [False, True])
def test_cli_wires_opt_in_and_refuses_release_before_requests(tmp_path, monkeypatch, release):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    case.inputs = {"steps": [{"path": "/vision/analyze", "checks": [{"pointer": "/ok", "value": True}],
                              "image": "offline-fixture.png",
                              "image_sha256": obs.data["evaluation_images"][0]["sha256"]}]}
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"version": "agent-eval-system-v1", "description": "offline fixture",
                                   "cases": [case.model_dump(mode="json")]}), encoding="utf-8")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "offline-fake-judge")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "never-send-this-test-secret")
    monkeypatch.setenv("EVAL_SUT_IDENTITY", "offline-fixture")
    monkeypatch.setattr(cli, "code_identity", lambda: {"head": "fixture", "dirty": False})
    observed = []
    monkeypatch.setattr(cli, "observe", lambda *args: observed.append(True) or obs)
    replies = iter([response(visual), response(decisions(gold))])
    calls = []
    monkeypatch.setattr(Judge, "_request", lambda *args: calls.append(True) or next(replies))
    args = ["--dataset", str(dataset), "--output", str(tmp_path / "reports"), "--split", "regression",
            "--judge", "provider", "--allow-provider", "--allow-api", "--judge-max-repairs", "0",
            "--judge-verify-visual-gold", "--judge-derive-gold-bindings"]
    if release:
        args.append("--release")
    assert cli.main(args) == (2 if release else 1)
    report = json.loads(next((tmp_path / "reports").glob("*/report.json")).read_text(encoding="utf-8"))
    if release:
        assert calls == observed == [] and report["operational_error"] == "ValueError"
    else:
        assert len(calls) == 2 and observed == [True]
        assert report["conditions"]["judge"]["gold_binding_rule"] == "derive-explicit-relations-v1"
        assert report["results"][0]["status"] == "failed"
        assert report["results"][0]["metrics"]["gold_coverage"] == 0
