from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from aiagent.evaluation import cli
from aiagent.evaluation.contracts import JudgeDiagnostic, Limit, read_json
from aiagent.evaluation.reporting import compare_reports
from aiagent.evaluation.scoring import score
from aiagent.evaluation.semantic import Judge, JudgeError
from tests.unit.test_evaluation_contracts import semantic_case
from tests.unit.test_evaluation_judge_protocol import observation, provider, response, verdict


@pytest.mark.parametrize("finish_reason", ["stop", "length"])
def test_judge_reports_only_safe_numeric_response_metadata(monkeypatch, finish_reason):
    reply = response(verdict(), finish_reason)
    reply.usage = SimpleNamespace(prompt_tokens=80, completion_tokens=4096,
                                 completion_tokens_details=SimpleNamespace(reasoning_tokens=3800))
    reply.choices[0].message.reasoning_content = "private analysis must never be persisted"
    judge, calls = provider(monkeypatch, [reply], max_repairs=0)
    result = score(semantic_case(), observation(), judge, "semantic@1")
    diagnostic = result.judge_diagnostics[0]
    assert diagnostic.output_chars == len(reply.choices[0].message.content)
    assert diagnostic.completion_tokens == 4096
    assert diagnostic.reasoning_tokens == 3800
    assert diagnostic.finish_reason == finish_reason
    assert result.status == ("passed" if finish_reason == "stop" else "judge_error")
    assert len(calls) == 1
    assert "private analysis" not in result.model_dump_json()
    assert "never-send-this-test-secret" not in result.model_dump_json()


@pytest.mark.parametrize("details", [None, SimpleNamespace(reasoning_tokens=None),
                                    SimpleNamespace(reasoning_tokens=-1),
                                    SimpleNamespace(reasoning_tokens=True),
                                    SimpleNamespace(reasoning_tokens="secret-value")])
def test_unknown_or_invalid_reasoning_usage_stays_null(monkeypatch, details):
    reply = response(verdict())
    reply.usage.completion_tokens_details = details
    judge, _ = provider(monkeypatch, [reply])
    result = score(semantic_case(), observation(), judge, "semantic@1")
    assert result.status == "passed"
    assert result.judge_diagnostics[0].reasoning_tokens is None
    assert "secret-value" not in result.model_dump_json()


def test_old_diagnostic_payload_remains_readable():
    diagnostic = JudgeDiagnostic.model_validate({"attempt": 1, "stage": "response", "code": "response_truncated"})
    assert diagnostic.output_chars == 0
    assert diagnostic.completion_tokens is None
    assert diagnostic.reasoning_tokens is None


@pytest.mark.parametrize("mode", ["default", "disabled"])
def test_deepseek_thinking_is_explicit_and_request_bound(monkeypatch, mode):
    import openai

    monkeypatch.setenv("EVAL_JUDGE_MODEL", "offline-fake-judge")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "fixture-only-secret")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "https://api.deepseek.com/v1")
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
    judge = Judge("provider", request_budget=1, max_output_tokens=1024, thinking_mode=mode)
    result = score(semantic_case(), observation(), judge, "semantic@1")
    assert result.status == "passed"
    assert judge.identity["thinking_mode"] == mode
    assert captured["client"]["max_retries"] == 0
    assert captured["request"]["max_tokens"] == 1024
    if mode == "disabled":
        assert captured["request"]["extra_body"] == {"thinking": {"type": "disabled"}}
    else:
        assert "extra_body" not in captured["request"]


@pytest.mark.parametrize("endpoint", ["", "https://api.openai.com/v1", "http://api.deepseek.com",
                                      "https://api.deepseek.com.attacker.invalid/v1",
                                      "https://user:secret@api.deepseek.com/v1"])
def test_vendor_extension_is_not_sent_to_other_or_unsafe_endpoints(monkeypatch, endpoint):
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", endpoint)
    with pytest.raises(JudgeError, match="thinking_mode_unsupported_endpoint"):
        Judge("provider", thinking_mode="disabled")


@pytest.mark.parametrize("mode", ["none", "manual"])
def test_thinking_override_requires_provider_mode(mode):
    with pytest.raises(JudgeError, match="thinking_mode_requires_provider"):
        Judge(mode, thinking_mode="disabled")


def test_thinking_override_changes_comparison_conditions(monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "offline-fake-judge")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "fixture-only-secret")
    default = Judge("provider").identity
    disabled = Judge("provider", thinking_mode="disabled").identity
    with pytest.raises(ValueError, match="incompatible"):
        compare_reports({"protocol": "fixture", "conditions": {"judge": default}},
                        {"protocol": "fixture", "conditions": {"judge": disabled}})


def run_selected(tmp_path, monkeypatch, *args):
    cases = [semantic_case().model_copy(update={"case_id": name, "split": split})
             for name, split in [("one", "regression"), ("two", "regression"), ("three", "dev")]]
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps({"version": "agent-eval-system-v1", "description": "fixture",
                                "cases": [case.model_dump(mode="json") for case in cases]}), encoding="utf-8")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "offline-fake-judge")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "fixture-only-secret")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "https://api.deepseek.com")
    observed = []

    def observer(case, *unused):
        observed.append(case.case_id)
        return observation()

    monkeypatch.setattr(cli, "observe", observer)
    monkeypatch.setattr(cli, "code_identity", lambda: {"head": "fixture", "dirty": False})
    monkeypatch.setattr(Judge, "_request", lambda *unused: response(verdict()))
    output = tmp_path / "reports"
    code = cli.main(["--dataset", str(path), "--output", str(output), "--split", "regression",
                     "--allow-provider", "--judge", "provider", *args])
    report = read_json(next(output.glob("*/report.json")))
    return code, report, observed


def test_case_selection_preserves_dataset_and_budgets_only_selected_cases(tmp_path, monkeypatch):
    code, report, observed = run_selected(tmp_path, monkeypatch, "--case-id", "two", "--case-id", "two",
                                          "--repeat", "2", "--judge-thinking", "disabled")
    assert code == 0 and observed == ["two", "two"]
    assert report["conditions"]["case_ids"] == ["two"]
    assert report["conditions"]["split"] == "regression"
    assert report["conditions"]["judge"]["request_budget"] == 4
    assert report["conditions"]["judge"]["thinking_mode"] == "disabled"
    assert report["judge_usage"]["logical_requests"] == 2
    assert report["summary"]["all"]["total"] == 2
    journal = next((tmp_path / "reports").glob("*/results.jsonl"))
    assert [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()] == report["results"]
    snapshot = read_json(journal.with_name("run.json"))
    assert snapshot["planned_evaluations"] == 2
    assert snapshot["conditions"] == report["conditions"]
    assert snapshot["code"] == report["code"]


def test_case_selection_keeps_dataset_order(tmp_path, monkeypatch):
    code, report, observed = run_selected(tmp_path, monkeypatch, "--case-id", "two", "--case-id", "one")
    assert code == 0 and observed == ["one", "two"]
    assert report["conditions"]["case_ids"] == ["one", "two"]


@pytest.mark.parametrize("case_id", ["missing", "three"])
def test_invalid_or_out_of_split_selection_stops_before_generation(tmp_path, monkeypatch, case_id):
    code, report, observed = run_selected(tmp_path, monkeypatch, "--case-id", case_id)
    assert code == 2 and observed == []
    assert report["operational_error"] == "ValueError"
    assert "judge_usage" not in report


def test_diagnostic_subset_cannot_masquerade_as_release_suite(tmp_path, monkeypatch):
    code, report, observed = run_selected(tmp_path, monkeypatch, "--case-id", "one", "--release")
    assert code == 2 and observed == []
    assert report["operational_error"] == "ValueError"


def test_without_filter_all_cases_in_split_run(tmp_path, monkeypatch):
    code, report, observed = run_selected(tmp_path, monkeypatch)
    assert code == 0 and observed == ["one", "two"]
    assert "case_ids" not in report["conditions"]
    assert report["conditions"]["judge"]["request_budget"] == 4


def test_legal_low_score_is_still_failed_without_quality_retry(monkeypatch):
    data = verdict()
    data["claims"][0]["truth"] = "unverifiable"
    data["covered_gold_ids"] = []
    data["coverage_claims"] = {}
    case = semantic_case()
    case.oracle.limits["fact_accuracy"] = Limit(minimum=1)
    judge, calls = provider(monkeypatch, [response(data)], request_budget=1)
    result = score(case, observation(), judge, "semantic@1")
    assert result.status == "failed"
    assert "metric_limit:fact_accuracy" in result.failures
    assert result.metrics["fact_unverifiable_rate"] == 1
    assert len(calls) == 1


def test_abnormal_exit_retains_completed_results_without_faking_a_report(tmp_path, monkeypatch):
    original = cli.evaluate_one
    calls = []

    def interrupted(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt("simulated process interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(cli, "evaluate_one", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_selected(tmp_path, monkeypatch)
    directory = next((tmp_path / "reports").iterdir())
    rows = [json.loads(line) for line in (directory / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["case_id"] for row in rows] == ["one"]
    assert rows[0]["status"] == "passed"
    snapshot = read_json(directory / "run.json")
    assert snapshot["complete"] is False
    assert snapshot["planned_evaluations"] == 2
    assert snapshot["conditions"]["split"] == "regression"
    assert snapshot["selected_cases"] == [{"case_id": "one", "group_id": "g"},
                                          {"case_id": "two", "group_id": "g"}]
    assert "never-send-this-test-secret" not in json.dumps(snapshot)
    assert not (directory / "report.json").exists()
    assert "answer" not in rows[0] and "raw_verdict" not in rows[0]


def test_run_snapshot_is_persisted_before_first_evaluation(tmp_path, monkeypatch):
    original = cli.evaluate_one
    seen = []

    def inspect(*args, **kwargs):
        directory = next((tmp_path / "reports").iterdir())
        snapshot = read_json(directory / "run.json")
        assert snapshot["selected_cases"] == [{"case_id": "one", "group_id": "g"},
                                              {"case_id": "two", "group_id": "g"}]
        assert not (directory / "report.json").exists()
        seen.append(args[0].case_id)
        return original(*args, **kwargs)

    monkeypatch.setattr(cli, "evaluate_one", inspect)
    code, _, _ = run_selected(tmp_path, monkeypatch)
    assert code == 0 and seen == ["one", "two"]
