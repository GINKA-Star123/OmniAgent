from __future__ import annotations

from unittest.mock import Mock

import pytest

from aiagent.graphs.memory_graph import MemoryRunner
from aiagent.memory.mem0_memory import MemoryHit
from aiagent.memory.memory_preferences import MemoryPreferenceStore
from aiagent.memory.memory_prompt import MemoryPromptBuilder
from aiagent.schemas.memory import MemoryCategory, MemoryImportance, MemoryWriteDecision


def _make_runner(tmp_path, *, facts=None, should_store=True, hits=None):
    memory = Mock()
    memory.search.return_value = list(hits or [])
    memory.list_pinned_records.return_value = []
    memory.add_approved.return_value = {"ok": True, "status": "stored"}
    policy = Mock()
    policy.decide_write.return_value = MemoryWriteDecision(
        should_store=should_store,
        category=MemoryCategory.PREFERENCE,
        importance=MemoryImportance.MEDIUM,
        facts=["用户喜欢川菜。"] if facts is None else facts,
        confidence=0.99,
        reason="synthetic policy decision",
    )
    runner = MemoryRunner(
        memory=memory,
        policy_service=policy,
        preference_store=MemoryPreferenceStore(path=tmp_path / "preferences.json"),
        write_dispatcher=Mock(),
        audit_log=Mock(),
        async_write_enabled=False,
    )
    return runner, memory, policy


def _write(runner):
    return runner.run_after_reply(
        user_id="u1", user_name="合成用户", session_id="s1", turn_id="t1",
        user_text="记住我喜欢川菜", assistant_text="好的",
        retrieval_query="用户偏好", planner_should_store_memory=True,
        memory_prompt_context="无长期记忆。",
    )


def test_safe_memory_passes_guard_and_writes_exactly_once(tmp_path):
    runner, memory, policy = _make_runner(tmp_path)
    result = _write(runner)
    assert result["store_result"]["status"] == "stored"
    memory.add_approved.assert_called_once()
    policy.decide_write.assert_called_once()
    assert memory.add_approved.call_args.args[0].text == "用户喜欢川菜。"
    assert "memory_store_plan" not in result


@pytest.mark.parametrize(("kind", "expected_status"), [
    ("policy_no", "skipped"), ("sensitive", "blocked"), ("duplicate", "duplicate"),
])
def test_policy_sensitive_and_duplicate_contrasts_never_write(tmp_path, kind, expected_status):
    kwargs = {}
    if kind == "policy_no":
        kwargs["should_store"] = False
    elif kind == "sensitive":
        kwargs["facts"] = ["用户的 API key 是 sk-abcdefghijklmnop"]
    else:
        kwargs["hits"] = [MemoryHit(id="old", memory="用户喜欢川菜。", score=0.99)]
    runner, memory, _ = _make_runner(tmp_path, **kwargs)
    result = _write(runner)
    assert result["store_result"]["status"] == expected_status
    memory.add_approved.assert_not_called()
    memory.add_turn.assert_not_called()


def test_guard_exception_is_fail_closed(tmp_path, monkeypatch):
    runner, memory, _ = _make_runner(tmp_path)

    def fail_guard(**kwargs):
        raise RuntimeError("synthetic guard failure")

    monkeypatch.setattr(runner.intake_service, "build_store_plan", fail_guard)
    result = _write(runner)
    memory.add_turn.assert_not_called()
    memory.add_approved.assert_not_called()
    assert result["store_result"]["status"] == "blocked"


def test_policy_exception_is_fail_closed(tmp_path):
    runner, memory, policy = _make_runner(tmp_path)
    policy.decide_write.side_effect = RuntimeError("synthetic policy failure")
    result = _write(runner)
    memory.add_turn.assert_not_called()
    memory.add_approved.assert_not_called()
    assert result["store_result"]["status"] == "skipped"


def test_disabled_memory_skips_read_pin_policy_and_write_then_can_reenable(tmp_path):
    runner, memory, policy = _make_runner(tmp_path)
    runner.set_user_preference(user_id="u1", long_term_enabled=False)
    retrieved = runner.retrieve_before_reply(user_id="u1", user_text="我喜欢什么？")
    written = _write(runner)
    assert retrieved["memory_prompt_context"] == "无长期记忆。"
    assert retrieved["memory_hits"] == []
    assert written["store_result"]["reason"] == "memory_disabled"
    memory.search.assert_not_called()
    memory.list_pinned_records.assert_not_called()
    memory.add_turn.assert_not_called()
    policy.decide_write.assert_not_called()

    runner.set_user_preference(user_id="u1", long_term_enabled=True)
    result = _write(runner)
    assert result["store_result"]["status"] == "stored"
    memory.search.assert_called_once()
    memory.list_pinned_records.assert_called_once()
    policy.decide_write.assert_called_once()
    memory.add_approved.assert_called_once()


def test_disabled_preference_is_scoped_to_user(tmp_path):
    runner, memory, _ = _make_runner(tmp_path)
    runner.set_user_preference(user_id="u1", long_term_enabled=False)
    runner.retrieve_before_reply(user_id="u2", user_text="我的偏好是什么？")
    memory.search.assert_called_once()
    assert memory.search.call_args.kwargs["user_id"] == "u2"


def test_deletion_is_reflected_in_next_prompt_without_stale_runner_cache(tmp_path):
    runner, memory, _ = _make_runner(tmp_path)
    records = [MemoryHit(id="synthetic-fruit", memory="用户喜欢榴莲。", score=0.99)]
    memory.search.side_effect = lambda **kwargs: list(records)
    before = runner.retrieve_before_reply(user_id="u1", user_text="我喜欢什么水果？")
    assert "榴莲" in before["memory_prompt_context"]
    records.clear()
    after = runner.retrieve_before_reply(user_id="u1", user_text="我喜欢什么水果？")
    assert "榴莲" not in after["memory_prompt_context"]
    assert after["memory_hits"] == []
    assert memory.search.call_count == 2


def test_memory_prompt_keeps_current_user_priority_instruction():
    prompt = MemoryPromptBuilder().build(
        hits=[MemoryHit(id="old", memory="用户喜欢川菜。", score=0.99)],
    )
    assert "以用户当前表达为准" in prompt.text
    assert "用户喜欢川菜" in prompt.text
