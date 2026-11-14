from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from aiagent.graphs.memory_graph import MemoryRunner
from aiagent.memory.approved_write import approve_plan
from aiagent.memory.mem0_memory import Mem0LongTermMemory, MemoryHit
from aiagent.memory.memory_preferences import MemoryPreferenceStore
from aiagent.memory.memory_safety import MemorySafetyFilter
from aiagent.memory.memory_write_audit import MemoryWriteAuditLog
from aiagent.memory.memory_write_dispatcher import MemoryWriteDispatcher
from aiagent.schemas.memory import MemoryCategory, MemoryStorePlan, MemoryWriteDecision
from aiagent.state.shared_state import (
    SharedStateConflictError,
    SharedStateOwnershipError,
    SharedStateUnavailableError,
)

CANARY = "CANARY_SECRET_NOT_APPROVED_2468"
FACT = "用户喜欢清淡的茶。"


class SDK:
    def __init__(self):
        self.calls, self.items = [], {}
        self.failure = False

    def add(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.failure:
            return {"ok": False, "status": "failed"}
        text = kwargs["messages"][0]["content"]
        record = {"id": "m1", "memory": text, "user_id": kwargs["user_id"],
                  "agent_id": kwargs["agent_id"], "metadata": deepcopy(kwargs["metadata"])}
        self.items["m1"] = record
        return {"results": [{"id": "m1", "event": "ADD", "memory": text}]}

    def get(self, key):
        return deepcopy(self.items.get(key))

    def update(self, key, text, metadata):
        self.calls.append({"operation": "update", "text": text, "metadata": deepcopy(metadata)})
        if self.failure:
            return {"ok": False, "status": "failed"}
        self.items[key].update(memory=text, metadata=deepcopy(metadata))
        return {"message": "updated"}

    def delete(self, key):
        self.calls.append({"operation": "delete", "key": key})
        self.items.pop(key, None)
        return {"message": "deleted"}


def adapter():
    memory = object.__new__(Mem0LongTermMemory)
    memory.memory, memory._lock = SDK(), RLock()
    memory.enable_graph = False
    memory.safety_filter = MemorySafetyFilter()
    return memory


def make_runner(tmp_path, *, facts=None, hits=None, dispatcher=None):
    memory = adapter()
    memory.search = Mock(return_value=hits or [])
    memory.list_pinned_records = Mock(return_value=[])
    policy = Mock()
    policy.decide_write.return_value = MemoryWriteDecision(
        should_store=True, category=MemoryCategory.PREFERENCE,
        facts=facts if facts is not None else [FACT], reason=CANARY,
        metadata={"raw_policy_response": CANARY},
    )
    worker = dispatcher or MemoryWriteDispatcher()
    runner = MemoryRunner(
        memory, policy, preference_store=MemoryPreferenceStore(tmp_path / "prefs.json"),
        write_dispatcher=worker, audit_log=MemoryWriteAuditLog(tmp_path / "audit.jsonl"),
    )
    return runner, memory, worker


def write(runner, *, background=False):
    method = runner.run_after_reply_async if background else runner.run_after_reply
    return method(
        user_id="u1", user_name=CANARY, session_id="s1", turn_id="t1",
        user_text=f"password={CANARY}; 我喜欢茶。", assistant_text=f"原始回复含 {CANARY}",
        retrieval_query="茶", planner_should_store_memory=True,
        metadata={"vision_memory_hint": CANARY, "policy_reason": CANARY},
    )


def test_approved_fact_not_raw_turn_reaches_actual_adapter(tmp_path, caplog):
    runner, memory, worker = make_runner(tmp_path)
    try:
        result = write(runner)
        assert result["store_result"]["status"] == "stored"
        assert result["metadata"]["memory_store_status"] == "done"
        assert float(result["metadata"]["memory_store_latency_ms"]) >= 0
        call = memory.memory.calls[0]
        assert call["messages"] == [{"role": "user", "content": FACT}]
        assert call["infer"] is False
        assert "prompt" not in call and "enable_graph" not in call
        assert call["user_id"] == "u1" and call["agent_id"] == "yzl"
        serialized = json.dumps({"call": call, "result": result}, ensure_ascii=False)
        assert CANARY not in serialized
        assert CANARY not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert CANARY not in caplog.text
    finally:
        worker.shutdown(wait=True)


@pytest.mark.parametrize("kind,status", [("safe", "stored"), ("secret", "blocked"),
                                         ("duplicate", "duplicate"), ("guard_error", "blocked")])
def test_memory_contrast_is_fail_closed(tmp_path, monkeypatch, kind, status):
    facts = [f"password={CANARY}"] if kind == "secret" else [FACT]
    hits = [MemoryHit(id="old", memory=FACT, score=1)] if kind == "duplicate" else []
    runner, memory, worker = make_runner(tmp_path, facts=facts, hits=hits)
    if kind == "guard_error":
        monkeypatch.setattr(runner.intake_service, "build_store_plan",
                            Mock(side_effect=RuntimeError(CANARY)))
    try:
        result = write(runner)
        assert result["store_result"]["status"] == status
        assert len(memory.memory.calls) == (1 if kind == "safe" else 0)
        assert CANARY not in json.dumps(result)
    finally:
        worker.shutdown(wait=True)


def test_missing_or_modified_plan_cannot_store(tmp_path):
    runner, memory, worker = make_runner(tmp_path)
    try:
        assert runner._store_node({})["store_result"]["status"] == "blocked"
        state = {"user_id": "u1", "agent_id": "yzl",
                 "write_decision": MemoryWriteDecision(should_store=True, facts=[FACT])}
        state.update(runner._guard_write_node(state))
        state["memory_store_plan"].memory_text = "用户喜欢咖啡。"
        assert runner._store_node(state)["store_result"]["status"] == "blocked"
        assert memory.memory.calls == []
    finally:
        worker.shutdown(wait=True)


def test_background_kwargs_contain_only_approved_payload(tmp_path):
    dispatcher = Mock()
    dispatcher.submit.return_value = {"ok": True, "status": "queued", "task_id": "task-1"}
    runner, memory, _ = make_runner(tmp_path, dispatcher=dispatcher)
    result = write(runner, background=True)
    assert result["store_result"]["status"] == "queued"
    assert set(dispatcher.submit.call_args.kwargs) == {"payload"}
    payload = dispatcher.submit.call_args.kwargs["payload"]
    assert payload.text == FACT
    assert CANARY not in json.dumps(asdict(payload))
    assert memory.memory.calls == []


@pytest.mark.parametrize("backend_result,expected", [
    ({"ok": True, "status": "stored"}, "done"),
    ({"ok": False, "status": "failed"}, "failed"),
    ({"ok": False, "status": "stored"}, "failed"),
    ({"ok": False, "status": "skipped"}, "skipped"),
])
def test_dispatcher_uses_business_result(backend_result, expected):
    dispatcher = MemoryWriteDispatcher()
    try:
        dispatcher.submit(lambda: backend_result)
        assert dispatcher.drain(5)
        assert dispatcher.status()["last"]["status"] == expected
    finally:
        dispatcher.shutdown(wait=True)


def test_sdk_failure_is_not_stored(tmp_path):
    runner, memory, worker = make_runner(tmp_path)
    memory.memory.failure = True
    try:
        result = write(runner)
        assert result["store_result"]["status"] == "failed"
        assert not result["store_result"]["ok"]
        assert runner.audit_log.tail(user_id="u1")[0].status == "failed"
    finally:
        worker.shutdown(wait=True)


def test_compiled_store_graph_uses_one_approved_sdk_write(tmp_path):
    runner, memory, worker = make_runner(tmp_path)
    try:
        result = runner.graph.invoke({
            "user_id": "u1", "agent_id": "yzl", "session_id": "s", "turn_id": "t",
            "user_text": f"password={CANARY}", "assistant_text": CANARY,
            "planner_should_store_memory": True,
        })
        assert result["store_result"]["status"] == "stored"
        for stage in ("memory_retrieve", "memory_decide_write", "memory_guard_write", "memory_store"):
            assert result["metadata"][f"{stage}_status"] == "done"
            assert float(result["metadata"][f"{stage}_latency_ms"]) >= 0
        assert len(memory.memory.calls) == 1
        assert CANARY not in json.dumps(memory.memory.calls)
    finally:
        worker.shutdown(wait=True)


def test_legacy_turn_and_disabled_graph_paths_do_not_write():
    memory = adapter()
    assert memory.add_turn("u1", "用户", FACT, "答复", "s", "t")["status"] == "blocked"
    safe_plan = MemoryStorePlan(should_store=True, status="ready", memory_text=FACT,
                               guard=MemorySafetyFilter().evaluate(FACT))
    payload = approve_plan(safe_plan, user_id="u1", agent_id="yzl")
    memory.enable_graph = True
    with pytest.raises(RuntimeError, match="memory_graph_requires_separate_approved_adapter"):
        memory.add_approved(payload)
    assert not memory.memory.calls


def test_preference_reason_cannot_persist_secret(tmp_path):
    preferences = MemoryPreferenceStore(tmp_path / "prefs.json")
    preferences.set(user_id="u1", long_term_enabled=False, reason=CANARY)
    assert CANARY not in (tmp_path / "prefs.json").read_text(encoding="utf-8")
    assert preferences.is_enabled("u1") is False


def test_edit_pin_merge_and_owner_are_preserved_without_metadata_secrets():
    memory = adapter()
    memory.memory.items = {
        key: {"id": key, "memory": FACT, "user_id": "u1", "agent_id": "yzl",
              "metadata": {"category": "preference", "memory_hint": CANARY}}
        for key in ("m1", "m2")
    }
    rejected = memory.update_memory(user_id="u2", memory_id="m1", memory_text="越权编辑")
    assert rejected["status"] == "not_found" and not memory.memory.calls
    assert memory.update_memory(user_id="u1", memory_id="m1", memory_text="用户喜欢清水。",
                                reason=CANARY, metadata={"secret": CANARY})["ok"]
    assert memory.set_memory_pinned(user_id="u1", memory_id="m1", pinned=True)["ok"]
    assert memory.merge_memories(user_id="u1", memory_ids=["m1", "m2"],
                                 merged_memory="用户偏好清水和淡茶。", reason=CANARY)["ok"]
    assert "m2" not in memory.memory.items
    assert CANARY not in json.dumps(memory.memory.calls)
    assert CANARY not in json.dumps(memory.memory.items)


def test_unknown_owner_and_sensitive_edit_are_rejected():
    memory = adapter()
    memory.memory.items["legacy"] = {"id": "legacy", "memory": FACT, "metadata": {}}
    assert memory.get_memory_record("legacy", "u1") is None
    memory.memory.items["m1"] = {"id": "m1", "memory": FACT, "user_id": "u1", "agent_id": "yzl"}
    assert memory.update_memory(user_id="u1", memory_id="m1",
                                memory_text=f"password={CANARY}")["status"] == "blocked"
    assert memory.delete_memory("m1", user_id="u2")["status"] == "not_found"
    assert memory.memory.calls == []


@pytest.mark.parametrize("operation", ["search", "list_pinned_records"])
@pytest.mark.parametrize("error_type", [
    SharedStateConflictError, SharedStateOwnershipError, SharedStateUnavailableError,
])
def test_retrieval_propagates_shared_errors_before_degradation(tmp_path, operation, error_type):
    runner, memory, worker = make_runner(tmp_path)
    getattr(memory, operation).side_effect = error_type("synthetic_shared_error")
    try:
        with pytest.raises(error_type):
            runner.retrieve_before_reply(user_id="u1", user_text="测试")
        assert memory.memory.calls == []
    finally:
        worker.shutdown(wait=True)


def test_retrieval_backend_error_body_is_not_public_metadata(tmp_path):
    runner, memory, worker = make_runner(tmp_path)
    memory.search.side_effect = RuntimeError(CANARY)
    try:
        result = runner.retrieve_before_reply(user_id="u1", user_text="测试")
        assert result["memory_hits"] == []
        assert result["metadata"]["memory_retrieve_status"] == "failed"
        assert CANARY not in json.dumps(result, ensure_ascii=False)
    finally:
        worker.shutdown(wait=True)


def test_installed_mem0_infer_false_branch_does_not_call_llm():
    from mem0 import Memory

    sdk = object.__new__(Memory)
    sdk.config = SimpleNamespace(llm=SimpleNamespace(config={}))
    sdk.llm = Mock()
    sdk.embedding_model = Mock()
    sdk.embedding_model.embed.return_value = [0.1, 0.2]
    sdk._create_memory = Mock(return_value="direct-1")
    result = Memory.add(sdk, messages=[{"role": "user", "content": FACT}],
                        user_id="u1", agent_id="yzl", infer=False,
                        metadata={"approval_version": "v12-b05"})
    assert result["results"][0]["memory"] == FACT
    assert result["results"][0]["event"] == "ADD"
    sdk.llm.assert_not_called()
    assert not sdk.llm.mock_calls
    sdk.embedding_model.embed.assert_called_once_with(FACT, "add")
    sdk._create_memory.assert_called_once()
