from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from aiagent.evaluation import adapters
from aiagent.evaluation.contracts import Observation
from aiagent.evaluation.reporting import compare_reports
from aiagent.evaluation.scoring import score
from aiagent.evaluation.semantic import Judge, JudgeError, Verdict
from aiagent.services.llm_service import LLMService
from tests.unit.test_evaluation_contracts import semantic_case
from tests.unit.test_evaluation_judge_protocol import observation, provider, response, verdict


@pytest.mark.parametrize("bindings,code", [
    ({}, "coverage_bindings_mismatch"),
    ({"unknown": ["星蓝"]}, "coverage_bindings_mismatch"),
    ({"color": []}, "coverage_claims_empty"),
    ({"color": ["星蓝", "星蓝"]}, "coverage_claim_duplicate"),
    ({"color": ["没有这个 claim"]}, "coverage_claim_missing"),
])
def test_coverage_requires_exact_traceable_claim_bindings(bindings, code):
    raw = verdict()
    raw["coverage_claims"] = bindings
    payload = Judge().build_payload(semantic_case(), observation())
    with pytest.raises(JudgeError, match=code):
        Judge.score_verdict(Verdict.model_validate(raw), payload)


@pytest.mark.parametrize("truth", ["incorrect", "unverifiable"])
def test_claim_cannot_simultaneously_be_noncorrect_and_cover_gold(monkeypatch, truth):
    raw = verdict()
    raw["claims"][0]["truth"] = truth
    judge, calls = provider(monkeypatch, [response(raw)], max_repairs=0)
    result = score(semantic_case(), observation(), judge, "coverage@1")
    assert result.status == "judge_error"
    assert result.error_code == "coverage_claim_not_correct"
    assert result.metrics == {} and len(calls) == 1


def test_coverage_binding_protocol_repair_can_lower_score_without_quality_retry(monkeypatch):
    bad = verdict()
    bad["claims"][0]["truth"] = "unverifiable"
    good = deepcopy(bad)
    good.update(covered_gold_ids=[], coverage_claims={})
    judge, calls = provider(monkeypatch, [response(bad), response(good)], request_budget=2)
    result = score(semantic_case(), observation(), judge, "coverage@1")
    assert result.status == "failed"
    assert result.metrics["gold_coverage"] == 0
    assert result.metrics["fact_unverifiable_rate"] == 1
    assert [item.code for item in result.judge_diagnostics] == ["coverage_claim_not_correct", "ok"]
    assert len(calls) == 2 and judge.usage["repair_requests"] == 1
    assert "coverage_claims" in calls[-1][-1]["content"]


def test_partial_coverage_and_extra_claims_preserve_denominator():
    case = semantic_case()
    case.oracle.gold["height"] = "身高160厘米。"
    obs = observation().model_copy(update={"answer": "星蓝。身高不清楚。"})
    raw = verdict()
    raw["claims"].append({"quote": "身高不清楚", "truth": "unverifiable", "support": "insufficient"})
    original = deepcopy(raw)
    metrics = Judge.score_verdict(Verdict.model_validate(raw), Judge().build_payload(case, obs))
    assert metrics["gold_coverage"] == .5
    assert metrics["fact_accuracy"] == .5 and metrics["claim_count"] == 2
    assert raw == original


def test_multiple_correct_claims_can_jointly_cover_a_single_goal():
    raw = verdict()
    raw["claims"].append({"quote": "160厘米", "support": "insufficient", "truth": "correct"})
    raw["coverage_claims"]["color"] = ["星蓝", "160厘米"]
    case = semantic_case()
    case.oracle.gold["color"] = "代表色星蓝，身高160厘米。"
    obs = observation().model_copy(update={"answer": "星蓝，160厘米。"})
    metrics = Judge.score_verdict(Verdict.model_validate(raw), Judge().build_payload(case, obs))
    assert metrics["gold_coverage"] == 1 and metrics["claim_count"] == 2


def test_coverage_cannot_bind_behavior_goals():
    case = semantic_case()
    judge = Judge(gold_kinds={case.case_id: {"color": "behavior"}})
    raw = verdict()
    raw.update(covered_gold_ids=[], behavior_checks={"color": "satisfied"})
    with pytest.raises(JudgeError, match="coverage_bindings_mismatch"):
        Judge.validate(Verdict.model_validate(raw), judge.build_payload(case, observation()))


def test_input_payload_cannot_disable_current_binding_validation():
    raw = verdict()
    raw["coverage_claims"] = {}
    payload = Judge().build_payload(semantic_case(), observation())
    payload["legacy_coverage"] = True
    with pytest.raises(JudgeError, match="coverage_bindings_mismatch"):
        Judge.validate(Verdict.model_validate(raw), payload)


def persona_case(scope="last_answer"):
    case = semantic_case().model_copy(update={"kind": "persona", "domain": "persona", "inputs": {
        "turns": ["我们是什么关系？", "如果我难过了呢？"], "persona": {}, "fact_scope": scope,
    }})
    case.oracle = case.oracle.model_copy(update={"gold": {"relationship": "是好朋友。"}})
    return case


def persona_observation():
    return Observation(scope="provider_component", answer="我会陪着你。", data={"history": [
        {"user": "我们是什么关系？", "answer": "我们是好朋友。"},
        {"user": "如果我难过了呢？", "answer": "我会陪着你。"},
    ]})


def relationship_verdict():
    return Verdict.model_validate({"claims": [{"quote": "我们是好朋友", "truth": "correct", "support": "insufficient"}],
        "covered_gold_ids": ["relationship"], "coverage_claims": {"relationship": ["我们是好朋友"]},
        "persona_violation": False, "style_score": 1})


def test_trajectory_is_explicit_not_a_silent_change_to_last_answer_coverage():
    obs = persona_observation()
    current = Judge().build_payload(persona_case(), obs)
    trajectory = Judge().build_payload(persona_case("trajectory"), obs)
    assert current["answer"] == obs.answer and current["fact_answers"] == [obs.answer]
    with pytest.raises(JudgeError, match="claim_quote_not_in_answer"):
        Judge.score_verdict(relationship_verdict(), current)
    assert Judge.score_verdict(relationship_verdict(), trajectory)["gold_coverage"] == 1
    assert trajectory["last_answer"] == obs.answer
    assert trajectory["question"] == "如果我难过了呢？"
    assert "我们是什么关系" not in trajectory["answer"]


@pytest.mark.parametrize("change", [
    [], [{"user": "错的问题", "answer": "我们是好朋友。"}],
    [{"user": "我们是什么关系？", "answer": "我们是好朋友。"},
     {"user": "如果我难过了呢？", "answer": "伪造末轮"}],
    [{"user": "我们是什么关系？", "answer": 12},
     {"user": "如果我难过了呢？", "answer": "我会陪着你。"}],
])
def test_trajectory_refuses_incomplete_or_mismatched_transcripts(change):
    obs = persona_observation()
    obs.data["history"] = change
    with pytest.raises(JudgeError, match="trajectory_history_invalid"):
        Judge().build_payload(persona_case("trajectory"), obs)


def test_trajectory_does_not_accept_user_quotes_or_claims_stitched_across_turns():
    payload = Judge().build_payload(persona_case("trajectory"), persona_observation())
    for quote in ["我们是什么关系", "好朋友。\n\n我会"]:
        raw = relationship_verdict().model_dump()
        raw["claims"][0]["quote"] = quote
        raw["coverage_claims"]["relationship"] = [quote]
        with pytest.raises(JudgeError, match="claim_quote_not_in_answer"):
            Judge.validate(Verdict.model_validate(raw), payload)


def test_scope_option_is_validated_and_default_remains_last_answer():
    assert adapters.PersonaInput(persona={}, turns=["问题"]).fact_scope == "last_answer"
    with pytest.raises(ValidationError):
        adapters.PersonaInput(persona={}, turns=["问题"], fact_scope="automatic")


def test_scope_overrides_cannot_be_compared_as_the_same_baseline():
    current = {"protocol": "fixture", "conditions": {}, "overrides_sha256": "trajectory-scope"}
    original = dict(current, overrides_sha256="last-answer-scope")
    with pytest.raises(ValueError, match="incompatible input overrides"):
        compare_reports(current, original)


@pytest.fixture
def fake_provider(monkeypatch):
    import config.settings as settings_module
    from aiagent.services import llm_service

    configured, services = [], []

    def settings():
        configured.append(1)
        config = SimpleNamespace(enable_mock_llm=False, llm_provider="openai")
        config.model_copy = lambda **kwargs: config
        return config

    def build(config):
        service = SimpleNamespace(close=Mock())
        services.append(service)
        return service

    monkeypatch.setattr(settings_module, "Settings", settings)
    monkeypatch.setattr(llm_service, "LLMService", build)
    return configured, services


def test_one_evaluation_session_reuses_settings_and_client_for_500_cases(fake_provider):
    configured, services = fake_provider
    with adapters.provider_session():
        first = adapters.strict_llm()
        for _ in range(500):
            assert adapters.strict_llm() is first
        first.close.assert_not_called()
    assert len(configured) == len(services) == 1
    first.close.assert_called_once_with()
    with adapters.provider_session():
        assert adapters.strict_llm() is not first
    assert len(configured) == len(services) == 2


def test_unused_or_nested_sessions_do_not_create_or_leak_global_clients(fake_provider):
    configured, services = fake_provider
    with adapters.provider_session():
        pass
    assert configured == services == []
    with adapters.provider_session():
        outer = adapters.strict_llm()
        with adapters.provider_session():
            inner = adapters.strict_llm()
            assert inner is not outer
        inner.close.assert_called_once_with()
        assert adapters.strict_llm() is outer
    outer.close.assert_called_once_with()


def test_session_closes_on_interrupt_and_does_not_hide_cleanup_failure(fake_provider):
    with pytest.raises(KeyboardInterrupt), adapters.provider_session():
        client = adapters.strict_llm()
        raise KeyboardInterrupt
    client.close.assert_called_once_with()
    with pytest.raises(RuntimeError, match="close failed"), adapters.provider_session():
        client = adapters.strict_llm()
        client.close.side_effect = RuntimeError("close failed")
    assert adapters._provider_session.get() is None


def test_service_close_is_lazy_and_idempotent():
    service = LLMService(SimpleNamespace())
    service.close()
    client = Mock()
    service._chat_model = SimpleNamespace(root_client=client)
    service.close()
    service.close()
    client.close.assert_called_once_with()
    assert service._chat_model is None


def test_judge_protocol_explicitly_changes_and_does_not_guess_old_bindings():
    assert Judge().identity["protocol"] == "judge-v8"
    raw = verdict()
    raw.pop("coverage_claims")
    with pytest.raises(JudgeError, match="coverage_bindings_mismatch"):
        Judge.score_verdict(Verdict.model_validate(raw), Judge().build_payload(semantic_case(), observation()))
    assert "coverage_claims" not in json.dumps(raw)
