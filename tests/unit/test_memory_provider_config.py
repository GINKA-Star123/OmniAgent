from __future__ import annotations

import pytest

from aiagent.memory import mem0_memory


def make_memory():
    return mem0_memory.Mem0LongTermMemory(
        llm_provider="openai",
        llm_model="deepseek-flash",
        llm_api_key_env="TEST_LLM_KEY",
        llm_base_url="https://api.deepseek.com/",
        embedder_provider="siliconflow",
        embedder_model="Qwen/Qwen3-VL-Embedding-8B",
        embedder_api_key_env="TEST_EMBEDDING_KEY",
        embedder_base_url="https://api.siliconflow.cn/v1",
        embedding_dims=4096,
        enable_graph=False,
    )


def test_memory_keeps_llm_and_embedding_endpoints_separate(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    monkeypatch.delenv("TEST_EMBEDDING_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "TEST_LLM_KEY=fixture-llm\nTEST_EMBEDDING_KEY=fixture-embedding\n",
        encoding="utf-8",
    )
    captured = {}
    sentinel = object()

    def fake_from_config(config):
        captured.update(config)
        return sentinel

    monkeypatch.setattr(mem0_memory.Memory, "from_config", fake_from_config)
    memory = make_memory()
    assert memory.memory is sentinel
    assert captured["llm"]["provider"] == "openai"
    assert captured["llm"]["config"]["model"] == "deepseek-flash"
    assert captured["llm"]["config"]["api_key"] == "fixture-llm"
    assert captured["llm"]["config"]["openai_base_url"] == "https://api.deepseek.com"
    assert captured["embedder"]["provider"] == "openai"
    assert captured["embedder"]["config"]["api_key"] == "fixture-embedding"
    assert captured["embedder"]["config"]["openai_base_url"] == "https://api.siliconflow.cn/v1"
    assert captured["vector_store"]["config"]["embedding_model_dims"] == 4096


def test_memory_refuses_openrouter_environment_override(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", "fixture-llm")
    monkeypatch.setenv("TEST_EMBEDDING_KEY", "fixture-embedding")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-router")

    def unexpected_from_config(config):
        pytest.fail("Mem0 must not initialize against a different endpoint")

    monkeypatch.setattr(mem0_memory.Memory, "from_config", unexpected_from_config)
    with pytest.raises(RuntimeError, match="Unset OPENROUTER_API_KEY"):
        make_memory()
