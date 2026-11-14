from __future__ import annotations

import json
import stat
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aiagent.evaluation import cli
from aiagent.evaluation.contracts import Case, Observation, read_json
from aiagent.evaluation.diagnostics import LocalJudgeDebug
from aiagent.evaluation.scoring import evaluate_one, score
from aiagent.evaluation.semantic import Judge, JudgeError
from tests.unit.test_evaluation_contracts import semantic_case


def verdict():
    return {"claims": [{"quote": "星蓝", "support": "supported", "truth": "correct",
                        "evidence_quotes": {"doc": "星蓝"}, "citation_ids": []}],
            "covered_gold_ids": ["color"], "coverage_claims": {"color": ["星蓝"]},
            "behavior_checks": {}, "persona_violation": False, "style_score": 1}


def observation():
    return Observation(scope="provider_component", answer="星蓝", evidence={"doc": "颜色是星蓝"})


def response(value, finish_reason="stop"):
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason,
                           message=SimpleNamespace(content=raw))],
                           usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7))


def provider(monkeypatch, replies, **kwargs):
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "offline-fake-judge")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "never-send-this-test-secret")
    judge = Judge("provider", **kwargs)
    calls = []
    replies = iter(replies)

    def request(messages):
        calls.append(deepcopy(messages))
        item = next(replies)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(judge, "_request", request)
    return judge, calls


@pytest.mark.parametrize(("change", "code"), [
    ({"covered_gold_ids": ["g1"]}, "gold_identifier_invalid"),
    ({"covered_gold_ids": ["color", "color"]}, "gold_identifier_duplicate"),
    ({"claims": []}, "covered_fact_claims_missing"),
    ({"behavior_checks": {"invented": "satisfied"}}, "behavior_identifiers_mismatch"),
    ({"claims": [{"quote": "暗红", "support": "insufficient", "truth": "incorrect"}]}, "claim_quote_not_in_answer"),
    ({"claims": [{"quote": "星蓝", "support": "supported", "truth": "correct"}]}, "supported_evidence_missing"),
    ({"claims": [{"quote": "星蓝", "support": "supported", "truth": "correct",
                  "evidence_quotes": {"doc": "暗红"}}]}, "evidence_quote_invalid"),
    ({"claims": [{"quote": "星蓝", "support": "insufficient", "truth": "correct",
                  "citation_ids": ["invented"]}]}, "answer_citation_invalid"),
    ({"claims": [{"quote": "星蓝", "support": "insufficient", "truth": "correct",
                  "visual_support": "visible"}]}, "visual_input_missing"),
])
def test_protocol_errors_have_stable_codes_and_no_raw_output(monkeypatch, change, code):
    data = verdict()
    data.update(change)
    judge, calls = provider(monkeypatch, [response(data)], max_repairs=0)
    result = score(semantic_case(), observation(), judge, "c@1")
    assert result.status == "judge_error"
    assert result.error_stage == "validation"
    assert result.error_code == code
    assert result.judge_diagnostics[0].finish_reason == "stop"
    assert len(calls) == 1
    text = result.model_dump_json()
    assert "never-send-this-test-secret" not in text
    assert "星蓝" not in text and "暗红" not in text


@pytest.mark.parametrize(("raw", "code"), [
    ("```json\n{}\n```", "verdict_json_invalid"),
    ('{"style_score":1,"style_score":0}', "verdict_json_invalid"),
    ('{"style_score":NaN}', "verdict_json_invalid"),
    ({"claims": "wrong-type"}, "verdict_schema_invalid"),
])
def test_invalid_json_and_schema_are_diagnosed(monkeypatch, raw, code):
    judge, _ = provider(monkeypatch, [response(raw)], max_repairs=0)
    result = score(semantic_case(), observation(), judge, "c@1")
    assert result.error_stage == "parse" and result.error_code == code


def test_format_repair_is_bounded_and_all_usage_is_counted(monkeypatch):
    broken = verdict()
    broken["coverage_claims"] = {}
    judge, calls = provider(monkeypatch, [response(broken), response(verdict())], request_budget=2)
    result = score(semantic_case(), observation(), judge, "c@1")
    assert result.status == "passed"
    assert [d.code for d in result.judge_diagnostics] == ["coverage_bindings_mismatch", "ok"]
    assert judge.usage["logical_requests"] == 2 and judge.usage["repair_requests"] == 1
    assert judge.usage["prompt_tokens_known"] == 22 and judge.usage["completion_tokens_known"] == 14
    assert "coverage_bindings_mismatch" in calls[1][-1]["content"]
    assert not any(item["role"] == "assistant" for item in calls[1])


def test_repeated_protocol_errors_stop_after_one_repair(monkeypatch):
    broken = verdict()
    broken["coverage_claims"] = {}
    judge, calls = provider(monkeypatch, [response(broken), response(broken)])
    result = score(semantic_case(), observation(), judge, "c@1")
    assert result.status == "judge_error" and len(calls) == 2


def test_global_request_budget_blocks_additional_calls(monkeypatch):
    broken = verdict()
    broken["coverage_claims"] = {}
    judge, calls = provider(monkeypatch, [response(broken)], request_budget=1)
    result = score(semantic_case(), observation(), judge, "c@1")
    assert result.error_stage == "budget" and result.error_code == "request_budget_exhausted"
    assert len(calls) == 1 and judge.usage["logical_requests"] == 1


def test_exhausted_judge_budget_does_not_generate_more_paid_answers(monkeypatch, tmp_path):
    judge, calls = provider(monkeypatch, [], request_budget=0)
    def forbidden_observer(*args):
        pytest.fail("generation must not start with an exhausted judge budget")

    result = evaluate_one(semantic_case(), tmp_path, "user", judge, "c@1", forbidden_observer)
    assert result.error_code == "request_budget_exhausted" and calls == []


@pytest.mark.parametrize("reason", ["stop", "length", "content_filter", "tool_calls", "unknown-provider-value"])
def test_finish_reason_is_recorded_safely(monkeypatch, reason):
    judge, calls = provider(monkeypatch, [response(verdict(), reason)], max_repairs=0)
    result = score(semantic_case(), observation(), judge, "c@1")
    assert result.judge_diagnostics[0].finish_reason == ("unknown" if reason == "unknown-provider-value" else reason)
    assert result.status == ("passed" if reason == "stop" else "judge_error")
    assert len(calls) == 1


@pytest.mark.parametrize("code", ["request_timeout", "request_authentication_failed", "request_rate_limited"])
def test_request_failures_are_not_automatically_retried(monkeypatch, code):
    judge, calls = provider(monkeypatch, [JudgeError("request", code)])
    result = score(semantic_case(), observation(), judge, "c@1")
    assert result.error_code == code and len(calls) == 1


def test_quality_failure_is_not_retried(monkeypatch):
    bad = verdict()
    bad["covered_gold_ids"] = []
    bad["coverage_claims"] = {}
    bad["claims"][0]["truth"] = "incorrect"
    judge, calls = provider(monkeypatch, [response(bad), response(verdict())])
    result = score(semantic_case(), observation(), judge, "c@1")
    assert result.status == "failed"
    assert result.error_code == "" and len(calls) == 1
    assert "metric_limit:gold_coverage" in result.failures


@pytest.mark.parametrize(("status", "expected"), [("satisfied", "passed"), ("violated", "failed"), ("not_observable", "failed")])
def test_behavior_is_checked_without_requiring_rule_recitation(monkeypatch, status, expected):
    case = semantic_case().model_copy(update={"case_id": "boundary", "domain": "persona", "kind": "persona",
        "inputs": {"turns": ["还没上传图片，聊聊配色吧。"],
                   "persona": {"persona_id": "test", "identity": {"name": "角色"}, "voice": {"ref_audio_path": "private.wav"}}}})
    case.oracle = case.oracle.model_copy(update={"gold": {"boundary": "不声称看到未上传图片。"}})
    data = {"claims": [], "covered_gold_ids": [], "behavior_checks": {"boundary": status},
            "persona_violation": False, "style_score": 1}
    judge, calls = provider(monkeypatch, [response(data)], gold_kinds={"boundary": {"boundary": "behavior"}})
    result = score(case, Observation(scope="provider_component", answer="你想用冷色还是暖色？"), judge, "b@1")
    assert result.status == expected and len(calls) == 1
    assert result.metrics["factual_gold_coverage"] is None
    assert result.metrics["behavior_pass_rate"] == (1 if status == "satisfied" else 0)
    payload = json.loads(calls[0][1]["content"][0]["text"])
    assert payload["question"] == "还没上传图片，聊聊配色吧。"
    assert payload["persona"] == {"persona_id": "test", "identity": {"name": "角色"}}
    assert payload["allowed_behavior_ids"] == ["boundary"] and payload["allowed_fact_ids"] == []


def test_generic_failure_does_not_leak_exception_message(monkeypatch):
    judge, _ = provider(monkeypatch, [ValueError("api_key=do-not-store")])
    result = score(semantic_case(), observation(), judge, "c@1")
    assert result.error_code == "judge_internal_error"
    assert "do-not-store" not in result.model_dump_json()


def test_debug_is_explicit_private_and_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("CLOUD_MODE", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "bare-credential-value")
    monkeypatch.setenv("TEST_SECRET", 'quoted"credential')
    debug = LocalJudgeDebug(tmp_path / ".debug")
    debug.write("../unsafe-key", 1, {"answer": 'bare-credential-value quoted"credential password=hidden', "count": 1},
                'api_key=another-secret sk-syntheticUnknownSecretValue')
    path = next((tmp_path / ".debug").glob("*.json"))
    text = path.read_text()
    for secret in ("bare-credential-value", "credential", "hidden", "another-secret", "sk-syntheticUnknownSecretValue"):
        assert secret not in text
    assert read_json(path)["payload"]["count"] == 1
    if __import__("os").name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_debug_refuses_nonlocal_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError):
        LocalJudgeDebug(tmp_path / ".debug")
    assert not (tmp_path / ".debug").exists()


def test_cli_debug_disabled_by_default_and_budget_in_conditions(tmp_path, monkeypatch):
    case = semantic_case()
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps({"version": "agent-eval-system-v1", "description": "fixture", "cases": [case.model_dump()]}))
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "offline-fake-judge")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "never-send-this-test-secret")
    monkeypatch.setattr(Judge, "_request", lambda *args: response(verdict()))
    monkeypatch.setattr(cli, "observe", lambda *args: observation())
    monkeypatch.setattr(cli, "code_identity", lambda: {"head": "test", "dirty": False})
    output = tmp_path / "reports"
    assert cli.main(["--dataset", str(path), "--output", str(output), "--judge", "provider",
                     "--allow-provider", "--judge-request-budget", "2"]) == 0
    report = read_json(next(output.glob("*/report.json")))
    assert report["conditions"]["judge"]["request_budget"] == 2
    assert report["judge_usage"]["logical_requests"] == 1
    assert not list(output.glob("*/.judge-debug"))
    serialized = json.dumps(report)
    assert "never-send-this-test-secret" not in serialized and "星蓝" not in serialized


def test_r3_annotations_match_gold_and_do_not_reclassify_food_identity():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "data/evaluation/project-20261026-r3"
    if not root.exists():
        pytest.skip("private frozen dataset unavailable")
    kinds = read_json(root / "judge-gold-kinds.json")
    cases = {row["case_id"]: Case.model_validate(row) for row in read_json(root / "provider-persona.json")["cases"]}
    judge = Judge(gold_kinds=kinds)
    for key in kinds:
        judge.build_payload(cases[key], Observation(scope="fixture"))
    assert "boundary" in judge.build_payload(cases["persona-yzl-03"], Observation(scope="fixture"))["allowed_fact_ids"]
    assert judge.build_payload(cases["persona-yzl-29"], Observation(scope="fixture"))["allowed_behavior_ids"] == ["boundary"]


def test_sdk_retries_are_disabled_and_output_tokens_are_bounded(monkeypatch):
    import openai

    monkeypatch.setenv("EVAL_JUDGE_MODEL", "offline-fake-judge")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "never-send-this-test-secret")
    captured = {}
    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def create(self, **kwargs):
            captured["request"] = kwargs
            return response(verdict())

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    judge = Judge("provider", request_budget=1, max_output_tokens=512)
    assert score(semantic_case(), observation(), judge, "c@1").status == "passed"
    assert captured["client"]["max_retries"] == 0
    assert captured["request"]["max_tokens"] == 512


def test_response_without_choices_has_a_stable_error(monkeypatch):
    empty = SimpleNamespace(choices=[], usage=None)
    judge, _ = provider(monkeypatch, [empty], max_repairs=0)
    result = score(semantic_case(), observation(), judge, "c@1")
    assert result.error_code == "response_choices_missing"
    assert result.error_stage == "response"
    assert judge.usage["responses_with_usage"] == 0


def test_behavior_cannot_be_reported_as_factual_coverage(monkeypatch):
    case = semantic_case()
    judge, _ = provider(monkeypatch, [response(verdict())], max_repairs=0,
                        gold_kinds={case.case_id: {"color": "behavior"}})
    result = score(case, observation(), judge, "c@1")
    assert result.error_code == "gold_identifier_invalid"


def test_annotation_typo_is_a_configuration_error_without_request(monkeypatch):
    judge, calls = provider(monkeypatch, [], gold_kinds={"semantic": {"typo": "behavior"}})
    result = score(semantic_case(), observation(), judge, "c@1")
    assert result.error_stage == "configuration" and result.error_code == "gold_annotation_unknown_id"
    assert calls == []


def test_annotation_generator_and_frozen_sidecar_match():
    from pathlib import Path

    from scripts.build_project_agent_eval_dataset import PERSONA_BEHAVIORAL_OBJECTIVES

    root = Path(__file__).resolve().parents[2] / "data/evaluation/project-20261026-r3"
    if not root.exists():
        pytest.skip("private frozen dataset unavailable")
    generated = {}
    for row in read_json(root / "catalog.json"):
        if row["dataset"] == "provider-persona.json" and row["category"] in PERSONA_BEHAVIORAL_OBJECTIVES:
            generated[row["case_id"]] = {key: "behavior" for key in PERSONA_BEHAVIORAL_OBJECTIVES[row["category"]]}
    assert generated == read_json(root / "judge-gold-kinds.json")
