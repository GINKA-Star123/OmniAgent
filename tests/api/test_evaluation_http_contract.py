import asyncio
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from aiagent.evaluation import http_support


def test_adapter_uses_existing_memory_api_contract(monkeypatch, tmp_path):
    from aiagent.graphs.memory_graph import MemoryRunner
    from aiagent.memory.memory_preferences import MemoryPreferenceStore
    from aiagent.memory.memory_write_audit import MemoryWriteAuditLog
    from aiagent.memory.memory_write_dispatcher import MemoryWriteDispatcher
    from apps.api.http_server import app
    from apps.api.routes import memory
    from apps.core.runtime import CoreRuntime

    # Exercise real routes, runtime methods and local persistence without model bootstrap.
    preferences = MemoryPreferenceStore(path=tmp_path / "preferences.json")
    long_term_memory = Mock(spec=["delete_all"])
    memory_runner = MemoryRunner(
        memory=long_term_memory,
        policy_service=Mock(spec=[]),
        preference_store=preferences,
        write_dispatcher=Mock(spec=MemoryWriteDispatcher),
        audit_log=MemoryWriteAuditLog(path=tmp_path / "audit.jsonl"),
    )
    main_runner = Mock(spec=["clear_user_threads"])
    main_runner.clear_user_threads.return_value = []
    agent_core = Mock(spec=["main_runner"])
    agent_core.main_runner = main_runner
    conversation_state = Mock(spec=["clear"])
    runtime = CoreRuntime(
        dispatcher=Mock(spec=[]), agent_core=agent_core,
        speaking_state=Mock(spec=[]), asr_listener=Mock(spec=[]),
        stream_state=Mock(spec=[]), long_term_memory=long_term_memory,
        memory_runner=memory_runner, source_router=Mock(spec=[]),
        llm_service=Mock(spec=[]), conversation_state=conversation_state,
        dialogue_manager=Mock(spec=[]), interrupt_manager=Mock(spec=[]),
        rag_pipeline=Mock(spec=[]),
    )
    monkeypatch.setattr(memory, "get_runtime", lambda: runtime)

    monkeypatch.setenv("EVAL_ISOLATED", "1")
    monkeypatch.setenv("EVAL_BASE_URL", "http://testserver")
    original = httpx.AsyncClient
    monkeypatch.setattr(http_support.httpx, "AsyncClient",
                        lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs))
    rows = asyncio.run(http_support.run_steps([
        {"method": "PUT", "path": "/memory/user/{user}/preferences", "body": {"long_term_enabled": False},
         "checks": [{"pointer": "/preferences/long_term_enabled", "value": False}]},
        {"method": "GET", "path": "/memory/user/{user}/preferences",
         "checks": [{"pointer": "/preferences/long_term_enabled", "value": False}]},
    ], [{"method": "DELETE", "path": "/memory/user/{user}",
         "checks": [{"pointer": "/ok", "value": True}]}], tmp_path, "eval-api-contract"))
    assert len(rows) == 2
    assert preferences.get("eval-api-contract").long_term_enabled is False
    assert MemoryPreferenceStore(path=preferences.path).get("eval-api-contract").source == "user"
    long_term_memory.delete_all.assert_called_once_with(user_id="eval-api-contract")
    main_runner.clear_user_threads.assert_called_once_with("eval-api-contract")
    conversation_state.clear.assert_called_once_with()


def test_wrong_200_is_not_a_pass():
    async def exercise():
        async def wrong(request):
            return httpx.Response(200, json={"ok": True, "reply": "错误答案"})

        async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(wrong)) as client:
            step = http_support.Step(path="/chat", checks=[{"pointer": "/reply", "value": "正确答案"}])
            with pytest.raises(AssertionError):
                await http_support.execute_step(client, step, Path("."))

    asyncio.run(exercise())


def test_polling_timeout_is_bounded():
    async def exercise():
        async def pending(request):
            return httpx.Response(200, json={"ready": False})

        async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(pending)) as client:
            step = http_support.Step(method="GET", path="/memory/user/eval-x/snapshot", poll_seconds=.01,
                                     checks=[{"pointer": "/ready", "value": True}])
            with pytest.raises(TimeoutError):
                await http_support.execute_step(client, step, Path("."))

    asyncio.run(exercise())


def test_cross_user_path_refused_before_network(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_ISOLATED", "1")
    monkeypatch.setenv("EVAL_BASE_URL", "http://evaluation.test")
    with pytest.raises(ValueError):
        asyncio.run(http_support.run_steps([
            {"method": "DELETE", "path": "/memory/user/real-user",
             "checks": [{"pointer": "/ok", "value": True}]}
        ], [], tmp_path, "eval-safe"))


def test_capture_is_used_by_later_step_and_cleanup_failure_is_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_ISOLATED", "1")
    monkeypatch.setenv("EVAL_BASE_URL", "http://evaluation.test")
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        if request.method == "DELETE":
            return httpx.Response(500, json={"ok": False})
        if request.method == "GET":
            return httpx.Response(200, json={"id": "record-1", "ok": True})
        return httpx.Response(200, json={"ok": True})

    original = httpx.AsyncClient
    monkeypatch.setattr(http_support.httpx, "AsyncClient",
                        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(RuntimeError, match="cleanup"):
        asyncio.run(http_support.run_steps([
            {"method": "GET", "path": "/memory/user/{user}/snapshot",
             "checks": [{"pointer": "/ok", "value": True}], "capture": {"id_memory": "/body/id"}},
            {"method": "PATCH", "path": "/memory/user/{user}/memories/{id_memory}",
             "body": {"memory": "合成偏好"}, "checks": [{"pointer": "/ok", "value": True}]},
        ], [{"method": "DELETE", "path": "/memory/user/{user}",
             "checks": [{"pointer": "/ok", "value": True}]}], tmp_path, "eval-capture"))
    assert "/memory/user/eval-capture/memories/record-1" in calls
