from __future__ import annotations

import logging
from importlib.metadata import version
from types import SimpleNamespace

import mem0.memory.main as mem0_main
from mem0 import Memory

from aiagent.memory import mem0_log_guard


class FakeVector:
    def __init__(self) -> None:
        self.item = SimpleNamespace(payload={
            "data": "old-synthetic-memory",
            "created_at": "2026-01-01T00:00:00+00:00",
            "user_id": "test-user",
            "agent_id": "test-agent",
        })
        self.updated = None

    def get(self, *, vector_id):
        assert vector_id == "test-id"
        return self.item

    def update(self, *, vector_id, vector, payload):
        assert vector_id == "test-id"
        self.updated = {"vector": vector, "payload": payload}


class FakeHistory:
    def __init__(self) -> None:
        self.calls = []

    def add_history(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def fake_memory(monkeypatch):
    instance = object.__new__(Memory)
    instance.vector_store = FakeVector()
    instance.db = FakeHistory()
    instance.embedding_model = SimpleNamespace(embed=lambda text, action: [0.25])
    instance._remove_memory_from_entity_store = lambda memory_id, filters: None
    entity_calls = []
    instance._link_entities_for_memory = lambda *args: entity_calls.append(args)
    monkeypatch.setattr(mem0_main, "lemmatize_for_bm25", lambda text: text)
    return instance, entity_calls


def test_locked_sdk_update_history_and_entity_side_effects(monkeypatch):
    # A version change requires source and privacy review, not an automatic skip.
    assert version("mem0ai") == "2.0.1"
    instance, entity_calls = fake_memory(monkeypatch)
    text = "approved-synthetic-canary"

    result = Memory._update_memory(instance, "test-id", text, {text: [0.25]},
                                   {"user_id": "test-user", "agent_id": "test-agent"})

    assert result == "test-id"
    assert instance.vector_store.updated["payload"]["data"] == text
    args, _ = instance.db.calls[0]
    assert args[:4] == ("test-id", "old-synthetic-memory", text, "UPDATE")
    assert entity_calls and entity_calls[0][1] == text


def test_guarded_and_unguarded_log_contrast(monkeypatch, caplog):
    instance, _ = fake_memory(monkeypatch)
    logger = logging.getLogger("mem0.memory.main")
    monkeypatch.setattr(logger, "filters", list(logger.filters))
    logger.filters[:] = [f for f in logger.filters if f.__class__.__name__ != "_SuppressMem0MainRecords"]
    text = "approved-synthetic-log-canary"

    with caplog.at_level(logging.INFO, logger="mem0.memory.main"):
        Memory._update_memory(instance, "test-id", text, {text: [0.25]})
        assert text in caplog.text
        caplog.clear()
        mem0_log_guard.install_mem0_log_guard()
        mem0_log_guard.install_mem0_log_guard()
        Memory._update_memory(instance, "test-id", text, {text: [0.25]})
        assert text not in caplog.text
        assert not [record for record in caplog.records if record.name == "mem0.memory.main"]
        assert sum(f.__class__.__name__ == "_SuppressMem0MainRecords" for f in logger.filters) == 1


def test_guard_does_not_suppress_other_loggers(monkeypatch, caplog):
    logger = logging.getLogger("mem0.memory.main")
    monkeypatch.setattr(logger, "filters", list(logger.filters))
    mem0_log_guard.install_mem0_log_guard()
    with caplog.at_level(logging.WARNING, logger="batch05.test.other"):
        logging.getLogger("batch05.test.other").warning("synthetic-operational-code")
    assert "synthetic-operational-code" in caplog.text
