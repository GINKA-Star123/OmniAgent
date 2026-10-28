from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from aiagent.evaluation.contracts import Case, Observation
from aiagent.evaluation.scoring import score
from aiagent.evaluation.semantic import GOLD_REVIEW_PROMPT, JUDGE_PROMPT, Judge, JudgeError, Verdict
from aiagent.persona.persona_guard import PersonaGuard
from aiagent.persona.persona_models import PersonaConfig
from aiagent.persona.persona_prompts import PersonaPromptBuilder
from tests.unit.test_evaluation_judge_protocol import provider, response


def visual_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    path = tmp_path / "offline-fixture.png"
    path.write_bytes(b"offline image bytes, never sent to a provider")
    case = Case(case_id="visual-target", group_id="visual-target", domain="vision", layer="component",
                kind="vision_api", inputs={"steps": [{"body": {"prompt": "只描述可见内容。"}}]},
                oracle={"semantic": True, "gold": {"object": "桌上有一盏绿色台灯。"},
                        "limits": {"gold_coverage": {"minimum": 1},
                                   "visual_unsupported_rate": {"maximum": 0}}})
    observation = Observation(scope="real_image_api", answer="桌上有一只绿色杯子。", data={
        "evaluation_images": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
    })
    visual = {"claims": [{"quote": observation.answer, "truth": "unverifiable", "support": "insufficient",
                          "visual_support": "visible", "evidence_quotes": {}, "citation_ids": []}],
              "covered_gold_ids": [], "coverage_claims": {}, "behavior_checks": {},
              "persona_violation": False, "style_score": 1}
    gold = deepcopy(visual)
    gold["claims"][0]["visual_support"] = "not_applicable"
    gold["coverage_assessments"] = {"object": {"gold_text": case.oracle.gold["object"],
        "relation": "not_addressed", "claim_quotes": []}}
    return case, observation, visual, gold


def test_pixel_and_gold_reviews_do_not_see_each_others_oracles(tmp_path, monkeypatch):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    judge, calls = provider(monkeypatch, [response(visual), response(gold)],
                            verify_visual_gold=True, request_budget=2)
    result = score(case, obs, judge, "visual@1")
    assert result.status == "failed" and result.metrics["gold_coverage"] == 0
    assert result.metrics["visual_grounded_rate"] == 1
    assert result.metrics["fact_unverifiable_rate"] == 1
    assert result.metrics["faithfulness"] is None
    assert [d.channel for d in result.judge_diagnostics] == ["visual", "gold"]
    pixel_payload = json.loads(calls[0][1]["content"][0]["text"])
    gold_payload = json.loads(calls[1][1]["content"][0]["text"])
    assert pixel_payload["gold"] == {} and pixel_payload["allowed_fact_ids"] == []
    assert len(calls[0][1]["content"]) == 2
    assert len(calls[1][1]["content"]) == 1
    assert gold_payload["images_sha256"] == []
    assert gold_payload["claim_quotes"] == [obs.answer]
    assert gold_payload["gold"] == case.oracle.gold
    assert "visual_support" not in gold_payload and "verdict" not in gold_payload
    assert calls[1][0]["content"] == GOLD_REVIEW_PROMPT
    assert judge.usage["logical_requests"] == 2 and judge.usage["repair_requests"] == 0


def test_correct_gold_review_keeps_pixel_contradictions(tmp_path, monkeypatch):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    obs.answer = "桌上有一盏绿色台灯。"
    for item in (visual, gold):
        item["claims"][0]["quote"] = obs.answer
    visual["claims"][0]["visual_support"] = "contradicted"
    gold["claims"][0]["truth"] = "correct"
    gold.update(covered_gold_ids=["object"], coverage_claims={"object": [obs.answer]})
    gold["coverage_assessments"]["object"].update(relation="entailed", claim_quotes=[obs.answer])
    judge, _ = provider(monkeypatch, [response(visual), response(gold)], verify_visual_gold=True)
    result = score(case, obs, judge, "visual@1")
    assert result.status == "failed"
    assert result.metrics["gold_coverage"] == result.metrics["fact_accuracy"] == 1
    assert result.metrics["visual_contradiction_rate"] == 1


@pytest.mark.parametrize("change,code", [
    ({"truth": "correct"}, "visual_channel_mixed"),
    ({"visual_support": "not_applicable"}, "visual_channel_mixed"),
])
def test_visual_phase_cannot_invent_gold_truth(tmp_path, monkeypatch, change, code):
    case, obs, visual, _ = visual_fixture(tmp_path, monkeypatch)
    visual["claims"][0].update(change)
    judge, calls = provider(monkeypatch, [response(visual)], verify_visual_gold=True, max_repairs=0)
    result = score(case, obs, judge, "visual@1")
    assert result.status == "judge_error" and result.error_code == code
    assert len(calls) == 1


@pytest.mark.parametrize("mutation,code", [
    ("drop", "gold_claims_mismatch"), ("invent", "claim_quote_not_in_answer"),
    ("pixels", "visual_input_missing"), ("citation", "answer_citation_invalid"),
])
def test_gold_phase_cannot_drop_claims_or_reuse_pixels(tmp_path, monkeypatch, mutation, code):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    if mutation == "drop":
        gold["claims"] = []
    elif mutation == "invent":
        gold["claims"][0]["quote"] = "不是实际回答"
    elif mutation == "pixels":
        gold["claims"][0]["visual_support"] = "visible"
    else:
        gold["claims"][0]["citation_ids"] = ["not-a-citation"]
    judge, calls = provider(monkeypatch, [response(visual), response(gold)],
                            verify_visual_gold=True, max_repairs=0)
    result = score(case, obs, judge, "visual@1")
    assert result.status == "judge_error" and result.error_code == code
    assert result.judge_diagnostics[-1].channel == "gold" and len(calls) == 2


def test_gold_protocol_repair_reuses_visual_result_and_can_remain_low_quality(tmp_path, monkeypatch):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    broken = dict(gold, claims=[])
    judge, calls = provider(monkeypatch, [response(visual), response(broken), response(gold)],
                            verify_visual_gold=True, request_budget=3)
    result = score(case, obs, judge, "visual@1")
    assert result.status == "failed" and result.metrics["gold_coverage"] == 0
    assert [d.channel for d in result.judge_diagnostics] == ["visual", "gold", "gold"]
    assert len(calls) == 3 and len(calls[1][1]["content"]) == len(calls[2][1]["content"]) == 1
    assert judge.usage["repair_requests"] == 1


def test_two_channels_share_a_hard_request_budget(tmp_path, monkeypatch):
    case, obs, visual, _ = visual_fixture(tmp_path, monkeypatch)
    judge, calls = provider(monkeypatch, [response(visual)], verify_visual_gold=True, request_budget=1)
    result = score(case, obs, judge, "visual@1")
    assert result.status == "judge_error" and result.error_code == "request_budget_exhausted"
    assert len(calls) == 1


def test_split_review_rejects_unimplemented_mixed_evidence_instead_of_changing_faithfulness(tmp_path, monkeypatch):
    case, obs, _, _ = visual_fixture(tmp_path, monkeypatch)
    obs.evidence = {"doc": "额外文字证据"}
    judge, calls = provider(monkeypatch, [], verify_visual_gold=True)
    result = score(case, obs, judge, "visual@1")
    assert result.error_code == "visual_gold_review_requires_fact_only" and calls == []


def test_plain_judge_keeps_single_request_and_identity_records_the_review_mode(monkeypatch):
    from tests.unit.test_evaluation_contracts import semantic_case
    from tests.unit.test_evaluation_judge_protocol import observation, verdict

    judge, calls = provider(monkeypatch, [response(verdict())])
    assert score(semantic_case(), observation(), judge, "text@1").status == "passed"
    assert len(calls) == 1 and judge.identity["verify_visual_gold"] is False
    assert Judge().identity["protocol"] == "judge-v8"


def test_coverage_entailment_is_not_the_reverse_of_claim_truth(tmp_path, monkeypatch):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    case.oracle.gold = {"object": "桌上有水果。"}
    obs.answer = "桌上有一盘苹果。"
    for item in (visual, gold):
        item["claims"][0]["quote"] = obs.answer
    gold.update(covered_gold_ids=["object"], coverage_claims={"object": [obs.answer]},
                coverage_assessments={"object": {"gold_text": case.oracle.gold["object"],
                    "relation": "entailed", "claim_quotes": [obs.answer]}})
    judge, _ = provider(monkeypatch, [response(visual), response(gold)], verify_visual_gold=True)
    result = score(case, obs, judge, "visual@1")
    assert result.status == "passed"
    assert result.metrics["gold_coverage"] == result.metrics["visual_grounded_rate"] == 1
    assert result.metrics["fact_accuracy_raw"] == result.metrics["fact_accuracy"] == 0
    assert result.metrics["fact_unverifiable_rate_raw"] == 1
    assert result.metrics["claim_count"] == 1


def test_partial_related_object_does_not_cover_all_gold_conditions(tmp_path, monkeypatch):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    case.oracle.gold = {"object": "窗边桌上有一盘苹果。"}
    obs.answer = "有水果。"
    for item in (visual, gold):
        item["claims"][0]["quote"] = obs.answer
    gold["claims"][0]["truth"] = "correct"
    gold["coverage_assessments"] = {"object": {"gold_text": case.oracle.gold["object"],
        "relation": "partial", "claim_quotes": [obs.answer]}}
    judge, _ = provider(monkeypatch, [response(visual), response(gold)], verify_visual_gold=True)
    result = score(case, obs, judge, "visual@1")
    assert result.status == "failed"
    assert result.metrics["fact_accuracy"] == 1 and result.metrics["gold_coverage"] == 0


@pytest.mark.parametrize("mutation,code", [
    ("missing", "coverage_assessments_mismatch"),
    ("unknown", "coverage_assessments_mismatch"),
    ("text", "coverage_gold_text_mismatch"),
    ("missing_claim", "coverage_claim_missing"),
    ("duplicate", "coverage_claim_duplicate"),
    ("unbound", "coverage_claims_empty"),
    ("unaddressed", "coverage_unaddressed_has_claims"),
    ("incorrect", "coverage_claim_incorrect"),
    ("binding", "coverage_assessment_bindings_mismatch"),
    ("partial", "coverage_entailed_ids_mismatch"),
])
def test_independent_coverage_proof_is_strict(tmp_path, monkeypatch, mutation, code):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    gold.update(covered_gold_ids=["object"], coverage_claims={"object": [obs.answer]})
    assessment = gold["coverage_assessments"]["object"]
    assessment.update(relation="entailed", claim_quotes=[obs.answer])
    if mutation == "missing":
        gold["coverage_assessments"] = {}
    elif mutation == "unknown":
        gold["coverage_assessments"]["extra"] = dict(assessment)
    elif mutation == "text":
        assessment["gold_text"] = "不是完整 gold"
    elif mutation == "missing_claim":
        assessment["claim_quotes"] = ["不是实际回答"]
    elif mutation == "duplicate":
        assessment["claim_quotes"] *= 2
    elif mutation == "unbound":
        assessment["claim_quotes"] = []
    elif mutation == "unaddressed":
        assessment["relation"] = "not_addressed"
    elif mutation == "incorrect":
        gold["claims"][0]["truth"] = "incorrect"
    elif mutation == "binding":
        gold["coverage_claims"] = {}
    else:
        assessment["relation"] = "partial"
    judge, calls = provider(monkeypatch, [response(visual), response(gold)],
                            verify_visual_gold=True, max_repairs=0)
    result = score(case, obs, judge, "visual@1")
    assert result.status == "judge_error" and result.error_code == code
    assert len(calls) == 2


def test_payload_cannot_enable_independent_coverage(tmp_path, monkeypatch):
    case, obs, _, gold = visual_fixture(tmp_path, monkeypatch)
    payload = Judge().build_payload(case, obs)
    payload["independent_coverage"] = True
    with pytest.raises(JudgeError, match="coverage_assessments_not_enabled"):
        Judge.score_verdict(Verdict.model_validate(gold), payload)
    with pytest.raises(JudgeError, match="coverage_modes_conflict"):
        Judge.score_verdict(Verdict.model_validate(gold), payload,
                            independent_coverage=True, legacy_coverage=True)


def test_guard_does_not_append_repeated_or_wrong_persona_tails():
    guard = PersonaGuard()
    replies = ["今天可以先选一个很短的片段，慢慢听一次，再休息。" * 3,
               "我喜欢的菜不变，不过我们可以分别选适合自己口味的食物。" * 3]
    for text in replies:
        result = guard.normalize(text)
        assert result.text == text and not result.changed and result.reasons == []
        assert guard.normalize_reply(result.text) == text
        assert "阿绫把重点" not in result.text
    assert guard.normalize_reply("嗯，嗯，好。") == "嗯，好。"
    assert guard.normalize_reply("作为AI，这只是角色扮演。") != "作为AI，这只是角色扮演。"


def test_persona_action_guidance_is_generic_and_does_not_force_old_facts_into_answers():
    config = PersonaConfig(persona_id="fixture", identity={"name": "桥声"}, style={"tone": "自然"},
                           rules={}, behavior={})
    prompt = PersonaPromptBuilder.build_system_prompt(config)
    assert "先给一项低负担、可直接执行的动作" in prompt
    assert "不为维持设定机械复述无关背景" in prompt
    assert "练歌" not in prompt and "天依" not in prompt
    assert "Markdown 标记、空格与标点" in JUDGE_PROMPT


def test_cli_accounts_for_two_visual_reviews_in_default_budget(tmp_path, monkeypatch):
    from aiagent.evaluation import cli
    from aiagent.evaluation.contracts import Result, read_json

    case, obs, _, _ = visual_fixture(tmp_path, monkeypatch)
    case.inputs = {"steps": [{"path": "/vision/analyze", "image": "offline-fixture.png",
                             "image_sha256": obs.data["evaluation_images"][0]["sha256"],
                             "checks": [{"pointer": "/ok", "value": True}]}]}
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps({"version": "agent-eval-system-v1", "description": "offline budget fixture",
                                "cases": [case.model_dump(mode="json")]}), encoding="utf-8")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "offline-only")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "offline-only")
    monkeypatch.setenv("EVAL_SUT_IDENTITY", "offline-fixture")
    monkeypatch.setattr(cli, "code_identity", lambda: {})
    monkeypatch.setattr(cli, "evaluate_one", lambda c, *args: Result(
        key=c.case_id + "@1", case_id=c.case_id, group_id=c.group_id, domain=c.domain, layer=c.layer,
        status="passed", scope="offline-fixture"))
    output = tmp_path / "reports"
    rc = cli.main(["--dataset", str(path), "--output", str(output), "--split", "regression",
                   "--allow-api", "--allow-provider", "--judge", "provider", "--judge-verify-visual-gold"])
    report = read_json(next(output.glob("*/report.json")))
    assert rc == 0
    assert report["conditions"]["judge"]["request_budget"] == 4
    assert report["conditions"]["judge"]["verify_visual_gold"] is True
