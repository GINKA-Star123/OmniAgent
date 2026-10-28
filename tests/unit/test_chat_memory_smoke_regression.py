from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from langchain_core.documents import Document

from aiagent.evaluation import http_support
from aiagent.evaluation.contracts import Case, Check, check_value
from aiagent.evaluation.scoring import evaluate_one
from aiagent.graphs.graph_model import LLMGraphInput
from aiagent.graphs.llm_graph import LLMRunner
from aiagent.graphs.rag_graph import RAGRunner
from aiagent.knowledge.query_normalizer import has_birthday_field
from aiagent.knowledge.rag_pipeline import RAGPipeline
from aiagent.knowledge.reranker import SimpleReranker
from aiagent.knowledge.retriever import HybridRetriever
from aiagent.memory.mem0_memory import Mem0LongTermMemory
from aiagent.memory.memory_safety import MemorySafetyFilter
from aiagent.schemas.memory import MemoryCategory, MemoryLayer


def doc(key, source, text):
    return Document(page_content=text, metadata={
        "chunk_id": key, "doc_id": source, "title": source,
        "file_name": source + ".md", "source_path": source + ".md",
    })


@pytest.mark.parametrize("name", ["小冰", "星桥", "猫尾++", "starlight_alt"])
def test_field_recall_survives_missing_bm25_and_misleading_vectors(name):
    target = doc("profile", name, "### 基本资料\n生日：9月17日")
    noise = [doc(f"noise-{i}", name, "声库版本发布于2014年5月29日，参考注释。") for i in range(20)]
    retriever = HybridRetriever(bm25_top_k=2, vector_top_k=2)
    retriever.build([*noise, target])
    retriever.bm25_retriever = Mock()
    retriever.bm25_retriever.invoke.return_value = noise[:2]
    vector = Mock()
    vector.similarity_search_with_score.return_value = [(d, .99) for d in noise[:2]]
    pipeline = RAGPipeline(Mock(), retriever, vector, SimpleReranker())
    pipeline.documents = [*noise, target]
    q = f"{name}生日是几月几日？请依据资料简短作答，不同声库版本不要混在一起，并标注来源。"
    rows = pipeline.retrieve(q, top_k=1)
    assert rows[0].chunk_id == "profile"
    assert rows[0].retrieval_sources == ["profile_field"]
    assert rows[0].bm25_rank is None and rows[0].vector_rank is None
    vector.similarity_search_with_score.assert_called_once_with(q, k=2)


def test_field_recall_never_steals_another_subject_or_creative_request():
    retriever = HybridRetriever(vector_top_k=0)
    retriever.build([doc("wrong", "猫尾+", "生日：9月17日")])
    retriever.bm25_retriever = None
    for query in ("猫尾++生日是几月几日", "猫尾+生日歌有哪些", "给猫尾+写一段生日祝福"):
        assert retriever.retrieve(query, Mock()) == []


@pytest.mark.parametrize("text,expected", [
    ("- **生日**：9月17日", True), ("生日：未知", True),
    ("2014年发布，并在生日会上演出", False),
])
def test_only_explicit_birthday_fields_are_lookup_candidates(text, expected):
    assert has_birthday_field(text) is expected


def test_planner_cannot_turn_a_date_lookup_into_a_music_query():
    runner = RAGRunner(Mock())
    raw = "星桥生日是几月几日？"
    assert runner._build_search_query(raw, "星桥生日歌曲", "活动") == raw


def test_production_prompt_prioritizes_facts_and_minimal_answer_over_planner():
    data = LLMGraphInput(thread_id="test", user_text="生日是几月几日？", reply_instruction="展开所有声库历史",
                         retrieved_context=["来源: 星桥.md\n### 基本资料\n生日：9月17日"])
    runtime = SimpleNamespace(build_system_prompt=lambda: "保持角色语气")
    prompt = LLMRunner._build_final_system_prompt(SimpleNamespace(), data, runtime, {})
    for rule in ("只回答用户明确询问的事实", "生日不等于产品发布日", "优先于角色风格与回复规划",
                 "不得覆盖用户当前任务", "来源: 星桥.md", "不能把局部未检索到说成全部资料都没有"):
        assert rule in prompt
    assert "优先服从 reply_instruction" not in prompt


class FakeMem0:
    def __init__(self):
        self.item = {"id": "m1", "memory": "用户最喜欢听亓官墨的歌曲。", "user_id": "u1", "agent_id": "yzl",
                     "metadata": {"category": "preference", "memory_layer": "preference",
                                  "memory_hint": "用户最喜欢听亓官墨的歌曲。",
                                  "memory_retrieval_query": "请记住亓官墨", "policy_reason": "亓官墨偏好",
                                  "memory_write_reason": "用户喜欢亓官墨", "source": "chat_turn"}}

    def get(self, key):
        return deepcopy(self.item) if self.item and key == self.item["id"] else None

    def get_all(self, **kwargs):
        return {"results": [deepcopy(self.item)] if self.item else []}

    def update(self, key, text, metadata):
        assert key == self.item["id"]
        self.item.update(memory=text, metadata=deepcopy(metadata))
        return {"message": "updated"}

    def delete_all(self, user_id, agent_id):
        assert user_id == "u1" and agent_id == "yzl"
        self.item = None
        return {"status": "ok"}


def memory():
    service = object.__new__(Mem0LongTermMemory)
    service.memory = FakeMem0()
    service._lock = RLock()
    service.safety_filter = MemorySafetyFilter()
    return service


def test_edit_pin_snapshot_and_delete_do_not_resurrect_old_fact():
    service = memory()
    updated = service.update_memory(user_id="u1", memory_id="m1", memory_text="用户最喜欢听莲华的歌曲。",
                                    category=MemoryCategory.PREFERENCE, layer=MemoryLayer.PREFERENCE)
    assert updated["ok"]
    assert service.set_memory_pinned(user_id="u1", memory_id="m1", pinned=True)["ok"]
    snapshot = service.get_snapshot("u1").model_dump(mode="json")
    for op, term in (("text_contains", "莲华"), ("text_absent", "亓官墨")):
        assert check_value(snapshot, Check(pointer="/layers", op=op, value=term))
    record = service.list_pinned_records("u1")[0]
    assert record.memory == record.metadata["memory_hint"] == "用户最喜欢听莲华的歌曲。"
    assert record.metadata["source"] == "chat_turn"
    assert service.delete_all("u1")["status"] == "ok"
    assert service.get_snapshot("u1").total == 0


def test_pin_only_preserves_current_fact_and_edit_remains_owner_scoped():
    service = memory()
    assert service.set_memory_pinned(user_id="u1", memory_id="m1", pinned=True)["ok"]
    assert service.get_memory_record(memory_id="m1", user_id="u1").memory == "用户最喜欢听亓官墨的歌曲。"
    before = deepcopy(service.memory.item)
    assert not service.update_memory(user_id="u2", memory_id="m1", memory_text="用户喜欢莲华")["ok"]
    assert service.memory.item == before


def test_poll_timeout_reports_failed_check_without_response_text(tmp_path):
    async def run():
        async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"secret": "private-original-text", "total": 1})
        )) as client:
            step = http_support.Step(method="GET", path="/memory/user/eval-x/snapshot", poll_seconds=.01,
                                     checks=[Check(pointer="/total", op="eq", value=0)])
            with pytest.raises(http_support.EvaluationPollTimeout) as raised:
                await http_support.execute_step(client, step, tmp_path)
            error = raised.value
            assert error.code == "api_poll_timeout"
            assert error.diagnostic == {"last_status": 200, "failed_check_indices": [1]}
            assert "private-original-text" not in str(error)
    asyncio.run(run())


def test_execution_diagnostics_survive_scoring_and_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_BASE_URL", "http://test")
    monkeypatch.setenv("EVAL_ISOLATED", "1")
    calls = []

    async def request(client, step, root):
        calls.append(step.method)
        return 200, {"ok": True, "total": 1, "private": "do-not-report"}

    monkeypatch.setattr(http_support, "one_request", request)
    case = Case(case_id="memory-failure", group_id="g", domain="memory", layer="task", kind="api",
                inputs={}, oracle={"required_terms": ["expected"]})

    def observer(*args):
        return asyncio.run(http_support.run_steps(
            [{"method": "GET", "path": "/memory/user/{user}/snapshot", "checks": [{"pointer": "/total", "value": 0}]}],
            [{"method": "DELETE", "path": "/memory/user/{user}", "checks": [{"pointer": "/ok", "value": True}]}],
            tmp_path, "eval-diagnostic"))

    result = evaluate_one(case, tmp_path, "eval-diagnostic", None, "memory-failure@1", observer)
    assert result.status == "error"
    assert result.error_stage == "api_step_1"
    assert result.error_code == "api_assertion_failed"
    assert result.execution_diagnostic["failed_check_indices"] == [1]
    assert calls == ["GET", "DELETE"]
    assert "do-not-report" not in json.dumps(result.model_dump())
