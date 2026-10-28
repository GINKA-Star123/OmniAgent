from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import rebuild_rag_cache


def test_rebuild_default_only_prints_plan(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["rebuild_rag_cache"])
    monkeypatch.setattr(rebuild_rag_cache, "Settings", lambda: SimpleNamespace(
        rag_embedding_provider="siliconflow",
        rag_embedding_model_name="fixture-model",
        rag_embedding_dimensions=4096,
    ))

    def unexpected(*args, **kwargs):
        raise AssertionError("Dry run must not back up files or resolve keys")

    monkeypatch.setattr(rebuild_rag_cache, "run_worker", unexpected)
    monkeypatch.setattr(rebuild_rag_cache, "resolve_named_secret", unexpected)
    rebuild_rag_cache.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["execute"] is False
    assert plan["model"] == "fixture-model"


def test_native_crash_is_reported_without_retry(monkeypatch, capsys):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=-11)

    monkeypatch.setattr(rebuild_rag_cache.subprocess, "run", run)
    assert rebuild_rag_cache.run_worker("preflight") == 2
    assert len(commands) == 1
    assert "--execute" not in commands[0]
    assert "faulthandler" in commands[0]
    assert json.loads(capsys.readouterr().out)["error_code"] == "native_crash"


def test_failed_preflight_never_runs_paid_build(monkeypatch):
    monkeypatch.setattr("sys.argv", ["rebuild_rag_cache", "--execute"])
    monkeypatch.setattr(rebuild_rag_cache, "Settings", lambda: SimpleNamespace(
        rag_embedding_provider="siliconflow", rag_embedding_model_name="fixture",
        rag_embedding_dimensions=4096, rag_index_manifest_path="",
    ))
    calls = []

    def worker(mode):
        calls.append(mode)
        return 2

    monkeypatch.setattr(rebuild_rag_cache, "run_worker", worker)
    assert rebuild_rag_cache.main() == 2
    assert calls == ["preflight"]


def test_preflight_cannot_be_combined_with_execute(monkeypatch):
    monkeypatch.setattr("sys.argv", ["rebuild_rag_cache", "--preflight", "--execute"])
    with pytest.raises(SystemExit) as error:
        rebuild_rag_cache.main()
    assert error.value.code == 2


def test_publish_preserves_old_cache_and_switches_all_files(tmp_path):
    cache = tmp_path / "knowledge"
    staging = tmp_path / ".knowledge-build-fixture"
    cache.mkdir()
    staging.mkdir()
    (cache / "old.txt").write_text("old", encoding="utf-8")
    (staging / "new.txt").write_text("new", encoding="utf-8")
    backup = rebuild_rag_cache.publish(staging, cache)
    assert backup is not None
    assert (backup / "old.txt").read_text() == "old"
    assert (cache / "new.txt").read_text() == "new"
    assert not (cache / "old.txt").exists()


def test_publish_failure_restores_previous_cache(monkeypatch, tmp_path):
    cache = tmp_path / "knowledge"
    staging = tmp_path / ".knowledge-build-fixture"
    cache.mkdir()
    staging.mkdir()
    (cache / "old.txt").write_text("old", encoding="utf-8")
    rename = Path.rename

    def fail_activation(self, destination):
        if self == staging:
            raise OSError("fixture activation failure")
        return rename(self, destination)

    monkeypatch.setattr(Path, "rename", fail_activation)
    with pytest.raises(OSError, match="fixture activation"):
        rebuild_rag_cache.publish(staging, cache)
    assert (cache / "old.txt").read_text() == "old"
    assert staging.exists()


def test_manifest_must_stay_inside_cache(monkeypatch, tmp_path):
    cache = tmp_path / "knowledge"
    monkeypatch.setattr(rebuild_rag_cache, "KNOWLEDGE_CACHE_DIR", cache)
    with pytest.raises(ValueError, match="inside"):
        rebuild_rag_cache.manifest_relative_path(SimpleNamespace(rag_index_manifest_path=str(tmp_path / "outside.json")))
    assert rebuild_rag_cache.manifest_relative_path(SimpleNamespace(rag_index_manifest_path="")) == Path("index_manifest.json")


@pytest.mark.parametrize("reserved", ["split_docs.json", "faiss_index", "faiss_index/manifest.json"])
def test_manifest_must_not_overwrite_index_files(monkeypatch, tmp_path, reserved):
    cache = tmp_path / "knowledge"
    monkeypatch.setattr(rebuild_rag_cache, "KNOWLEDGE_CACHE_DIR", cache)
    with pytest.raises(ValueError, match="reserved"):
        rebuild_rag_cache.manifest_relative_path(SimpleNamespace(rag_index_manifest_path=str(cache / reserved)))


def configure_offline_rebuild(monkeypatch, tmp_path):
    from langchain_core.embeddings import DeterministicFakeEmbedding

    from aiagent.knowledge.vector_store import LangChainVectorStore

    cache = tmp_path / "knowledge"
    knowledge = tmp_path / "public"
    cache.mkdir()
    knowledge.mkdir()
    (cache / "previous.txt").write_text("do not lose", encoding="utf-8")
    (knowledge / "fixture.md").write_text("# Fixture\nA local offline document for index rebuild.", encoding="utf-8")
    monkeypatch.setattr(rebuild_rag_cache, "KNOWLEDGE_CACHE_DIR", cache)
    monkeypatch.setattr(rebuild_rag_cache, "KNOWLEDGE_PUBLIC_DIR", knowledge)
    monkeypatch.setattr(rebuild_rag_cache, "resolve_named_secret", lambda name: "offline-placeholder")
    monkeypatch.setattr(LangChainVectorStore, "_build_embeddings", lambda *a, **kw: DeterministicFakeEmbedding(size=2))
    settings = SimpleNamespace(
        rag_embedding_provider="openai", rag_embedding_api_key_env="OFFLINE_KEY",
        rag_embedding_base_url="https://offline.invalid/v1", rag_index_manifest_path="",
        rag_bm25_top_k=2, rag_vector_top_k=2, rag_embedding_model_name="fixture",
        rag_embedding_model_path="", rag_embedding_device="cpu", rag_embedding_local_files_only=True,
        rag_embedding_batch_size=2, rag_embedding_dimensions=2,
        rag_chunk_size=520, rag_chunk_overlap=80, rag_final_top_k=2,
    )
    return cache, settings


def test_full_staged_rebuild_with_offline_vectors(monkeypatch, tmp_path, capsys):
    cache, settings = configure_offline_rebuild(monkeypatch, tmp_path)
    rebuild_rag_cache.rebuild(settings)
    assert (cache / "faiss_index/index.faiss").is_file()
    assert (cache / "faiss_index/index.pkl").is_file()
    manifest = json.loads((cache / "index_manifest.json").read_text())
    assert manifest["docs_index_path"] == str(cache / "split_docs.json")
    assert manifest["faiss_dir"] == str(cache / "faiss_index")
    backups = list(tmp_path.glob("knowledge-backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "previous.txt").read_text() == "do not lose"
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[-1]["stage"] == "complete"
    assert output[-1]["freshness"]["status"] == "fresh"
    assert output[-1]["stats"]["chunk_count"] == output[-1]["stats"]["vector_count"] > 0


def test_build_failure_leaves_previous_cache_unchanged(monkeypatch, tmp_path):
    from aiagent.knowledge.vector_store import LangChainVectorStore

    cache, settings = configure_offline_rebuild(monkeypatch, tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("fixture embedding failure")

    monkeypatch.setattr(LangChainVectorStore, "build", fail)
    with pytest.raises(RuntimeError, match="fixture embedding"):
        rebuild_rag_cache.rebuild(settings)
    assert sorted(p.name for p in cache.iterdir()) == ["previous.txt"]
    assert (cache / "previous.txt").read_text() == "do not lose"
    assert list(tmp_path.glob(".knowledge-build-*/split_docs.json"))
    assert not list(tmp_path.glob("knowledge-backup-*"))


def test_manifest_failure_blocks_publication(monkeypatch, tmp_path):
    from aiagent.knowledge import index_manifest

    cache, settings = configure_offline_rebuild(monkeypatch, tmp_path)
    monkeypatch.setattr(index_manifest, "save_index_manifest", lambda *args: False)
    with pytest.raises(RuntimeError, match="Cannot save"):
        rebuild_rag_cache.rebuild(settings)
    assert (cache / "previous.txt").read_text() == "do not lose"
    assert not (cache / "faiss_index").exists()


def test_preflight_uses_only_mock_http(monkeypatch, capsys):
    import socket

    def unexpected(*args, **kwargs):
        raise AssertionError("Preflight must never open a network socket")

    monkeypatch.setattr(socket.socket, "connect", unexpected)
    rebuild_rag_cache.preflight(2)
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["stage"] == "preflight_passed"


def test_probe_dry_run_never_starts_worker(monkeypatch):
    monkeypatch.setattr("sys.argv", ["rebuild_rag_cache", "--probe-provider", "--probe-items", "32"])
    monkeypatch.setattr(rebuild_rag_cache, "Settings", lambda: SimpleNamespace(
        rag_embedding_provider="siliconflow", rag_embedding_model_name="fixture", rag_embedding_dimensions=4096,
    ))

    def unexpected(*args):
        raise AssertionError("Probe still requires --execute")

    monkeypatch.setattr(rebuild_rag_cache, "run_worker", unexpected)
    assert rebuild_rag_cache.main() == 0


def test_probe_runs_preflight_then_probe_never_build(monkeypatch):
    monkeypatch.setattr("sys.argv", ["rebuild_rag_cache", "--execute", "--probe-provider", "--probe-items", "32"])
    monkeypatch.setattr(rebuild_rag_cache, "Settings", lambda: SimpleNamespace(
        rag_embedding_provider="siliconflow", rag_embedding_model_name="fixture", rag_embedding_dimensions=4096,
    ))
    calls = []

    def worker(mode, *args):
        calls.append((mode, args))
        return 0

    monkeypatch.setattr(rebuild_rag_cache, "run_worker", worker)
    assert rebuild_rag_cache.main() == 0
    assert calls == [("preflight", ()), ("probe", (32,))]


@pytest.mark.parametrize("items", [0, -1, 33])
def test_probe_budget_must_be_bounded(monkeypatch, items):
    monkeypatch.setattr("sys.argv", ["rebuild_rag_cache", "--execute", "--probe-provider", "--probe-items", str(items)])
    with pytest.raises(SystemExit) as error:
        rebuild_rag_cache.main()
    assert error.value.code == 2


@pytest.mark.parametrize("status", [200, 429])
def test_probe_is_one_synthetic_request_without_cache_writes(monkeypatch, tmp_path, capsys, status):
    import httpx
    from openai import OpenAI, RateLimitError

    from aiagent.knowledge.vector_store import OpenAICompatibleEmbeddings

    calls = []

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if status == 429:
            return httpx.Response(429, json={"error": {"message": "private-provider-sentinel"}})
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": [0.1, 0.2]} for i in range(len(payload["input"]))
        ]})

    embeddings = OpenAICompatibleEmbeddings("fixture", "offline-placeholder", "https://offline.invalid/v1", dimensions=2)
    embeddings.client.close()
    embeddings.client = OpenAI(api_key="offline-placeholder", max_retries=2,
                               http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(rebuild_rag_cache, "configured_vector_store", lambda settings: SimpleNamespace(embeddings=embeddings))
    cache = tmp_path / "must-not-be-created"
    monkeypatch.setattr(rebuild_rag_cache, "KNOWLEDGE_CACHE_DIR", cache)
    settings = SimpleNamespace(rag_embedding_provider="siliconflow")
    if status == 429:
        with pytest.raises(RateLimitError) as error:
            rebuild_rag_cache.probe_provider(settings, 32)
        safe = rebuild_rag_cache.safe_failure(error.value)
        assert safe["http_status"] == 429
        assert "private-provider" not in json.dumps(safe)
    else:
        rebuild_rag_cache.probe_provider(settings, 32)
        assert json.loads(capsys.readouterr().out.splitlines()[-1])["stage"] == "provider_probe_passed"
    assert len(calls) == 1
    assert len(calls[0]["input"]) == 32
    assert all(text.startswith("Offline evaluation embedding probe ") for text in calls[0]["input"])
    assert not cache.exists()


def test_safe_failure_preserves_validation_details_without_source_or_locals():
    from aiagent.knowledge.vector_store import EmbeddingValidationError

    try:
        raise EmbeddingValidationError("embedding_response_dimension_mismatch", "Embedding response dimension mismatch",
                                       expected_dimensions=4096, actual_dimensions=1024)
    except EmbeddingValidationError as exc:
        result = rebuild_rag_cache.safe_failure(exc)
    assert result["error_code"] == "embedding_response_dimension_mismatch"
    assert result["diagnostics"]["actual_dimensions"] == 1024
    assert result["error_locations"][-1]["file"] == "test_rebuild_rag_cache.py"
    assert set(result["error_locations"][-1]) == {"file", "line", "function"}


def test_generic_failure_does_not_print_exception_message():
    try:
        raise ValueError("private-key-and-body-sentinel")
    except ValueError as exc:
        result = rebuild_rag_cache.safe_failure(exc)
    assert "private-key-and-body-sentinel" not in json.dumps(result)
    assert result["error_locations"][-1]["function"] == "test_generic_failure_does_not_print_exception_message"


def test_independent_paths_are_forwarded_to_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(rebuild_rag_cache, "KNOWLEDGE_CACHE_DIR", tmp_path / "output")
    monkeypatch.setattr(rebuild_rag_cache, "KNOWLEDGE_PUBLIC_DIR", tmp_path / "corpus")
    commands = []
    monkeypatch.setattr(rebuild_rag_cache.subprocess, "run", lambda command, **kw: (
        commands.append(command) or SimpleNamespace(returncode=0)))
    assert rebuild_rag_cache.run_worker("build") == 0
    assert commands[0][commands[0].index("--cache-dir") + 1] == str(tmp_path / "output")
    assert commands[0][commands[0].index("--knowledge-dir") + 1] == str(tmp_path / "corpus")


def test_overlapping_cache_and_corpus_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(rebuild_rag_cache, "KNOWLEDGE_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(rebuild_rag_cache, "KNOWLEDGE_PUBLIC_DIR", tmp_path / "public")
    monkeypatch.setattr("sys.argv", ["rebuild", "--cache-dir", str(tmp_path / "public/cache")])
    with pytest.raises(SystemExit) as error:
        rebuild_rag_cache.main()
    assert error.value.code == 2


@pytest.mark.parametrize("timeout, code", [(True, "embedding_provider_timeout"),
                                         (False, "embedding_provider_connection_error")])
def test_network_errors_have_stable_codes_without_request_data(timeout, code):
    import httpx
    from openai import APIConnectionError, APITimeoutError

    request = httpx.Request("POST", "https://private-host-sentinel.invalid", headers={"Authorization": "secret-sentinel"})
    error = APITimeoutError(request=request) if timeout else APIConnectionError(request=request)
    result = rebuild_rag_cache.safe_failure(error)
    assert result["error_code"] == code
    assert "sentinel" not in json.dumps(result)
