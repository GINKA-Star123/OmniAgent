import asyncio
from copy import deepcopy

import httpx

from aiagent.evaluation.contracts import Case, Observation
from aiagent.evaluation.load import load_summary, run_load
from aiagent.evaluation.scoring import evaluate_one, score
from aiagent.evaluation.semantic import Judge
from scripts.build_agent_eval_dataset import offline_dataset


def fixture_case(case_id):
    raw = next(row for row in offline_dataset()["cases"] if row["case_id"] == case_id)
    return Case.model_validate(deepcopy(raw))


def test_correct_and_wrong_ranking_are_distinguished():
    case = fixture_case("rag-known")
    good = score(case, Observation(scope="offline_bm25", retrieved=["starlight.txt"]), Judge(), "rag@1")
    bad = score(case, Observation(scope="offline_bm25", retrieved=["alternate.txt"]), Judge(), "rag@1")
    assert good.status == "passed"
    assert bad.status == "failed"


def test_retrieval_only_identity_confirmation_is_a_failure():
    case = fixture_case("vision-retrieval-only")
    bad = Observation(scope="offline_policy", data={"confirmed": True, "confirmed_ids": ["starlight"],
                                                  "avoid_identity_assertion": False})
    assert score(case, bad, Judge(), "vision@1").status == "failed"


def test_sensitive_memory_persist_intent_is_rejected():
    case = fixture_case("memory-sensitive")
    bad = Observation(scope="offline_policy", label="store", data={"status": "ready", "should_store": True})
    assert score(case, bad, Judge(), "memory@1").status == "failed"


def test_forbidden_and_out_of_order_trajectory_fails():
    case = fixture_case("persona-refusal-route")
    bad = Observation(scope="offline_refusal_graph", answer="保持设定",
                      events=["build_refusal_packet", "prepare_context", "run_llm_graph"])
    result = score(case, bad, Judge(), "graph@1")
    assert result.status == "failed"
    assert any(item.startswith("event_order:") for item in result.failures)
    assert any(item.startswith("event_forbidden:") for item in result.failures)


def test_execution_failure_is_preserved_without_error_message_leak(tmp_path):
    def failing(*args):
        raise RuntimeError("password=do-not-save")

    row = evaluate_one(fixture_case("memory-safe"), tmp_path, "eval-user", Judge(), "c@1", failing)
    assert row.status == "error"
    assert row.error_type == "RuntimeError"
    assert "password" not in str(row.model_dump())


def test_200_wrong_answer_does_not_count_as_goodput(monkeypatch):
    monkeypatch.setenv("EVAL_ISOLATED", "1")
    monkeypatch.setenv("EVAL_BASE_URL", "http://evaluation.test")

    async def handler(request):
        if request.method == "DELETE":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={"ok": True, "reply": "暗红"})

    report = asyncio.run(run_load(rate=1000, total=3, workers=1, queue_size=10, users=1,
                                 timeout=1, slo_ms=1000, text="代表色？", required=("星蓝",), forbidden=(),
                                 transport=httpx.MockTransport(handler)))
    assert report["http_2xx_qps"] > 0
    assert report["rule_goodput_qps"] == 0
    assert report["rule_slo_pass_rate"] == 0


def test_timeout_dropped_and_wrong_answers_are_not_removed():
    rows = [
        {"sent": True, "state": "completed", "http_2xx": True, "rule_ok": True, "elapsed_ms": 1},
        {"sent": True, "state": "timeout", "http_2xx": False, "rule_ok": False, "elapsed_ms": 1000},
        {"sent": False, "state": "dropped", "http_2xx": False, "rule_ok": False, "elapsed_ms": 0},
        {"sent": True, "state": "completed", "http_2xx": True, "rule_ok": False, "elapsed_ms": 1},
    ]
    summary = load_summary(rows, 1, 100)
    assert summary["total_scheduled"] == 4
    assert summary["rule_slo_pass_rate"] == .25
    assert summary["timeout_n"] == 1
    assert summary["p99_small_sample"]


def test_http_timeout_is_recorded_and_cleanup_still_happens(monkeypatch):
    monkeypatch.setenv("EVAL_ISOLATED", "1")
    monkeypatch.setenv("EVAL_BASE_URL", "http://evaluation.test")
    deleted = []

    async def handler(request):
        if request.method == "DELETE":
            deleted.append(request.url.path)
            return httpx.Response(200, json={"ok": True})
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    report = asyncio.run(run_load(rate=10, total=1, workers=1, queue_size=1, users=1,
                                 timeout=1, slo_ms=1000, text="q", required=("a",), forbidden=(),
                                 transport=httpx.MockTransport(handler)))
    assert report["timeout_n"] == 1
    assert report["rule_goodput_qps"] == 0
    assert len(deleted) == 1
