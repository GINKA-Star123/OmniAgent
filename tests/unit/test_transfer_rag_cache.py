from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import pytest
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from aiagent.knowledge.index_manifest import build_index_manifest, save_index_manifest
from scripts import transfer_rag_cache as transfer


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Transfer must be offline")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    corpus = tmp_path / "public"
    (corpus / "folder").mkdir(parents=True)
    (corpus / "folder/doc.md").write_text("# Fixture\nOffline knowledge.", encoding="utf-8")
    cache = tmp_path / "export"
    cache.mkdir()
    docs = [Document(page_content="Offline knowledge.", metadata={"source_path": "folder\\doc.md", "chunk_id": "stable-id"})]
    store = FAISS.from_documents(docs, DeterministicFakeEmbedding(size=2))
    store.save_local(str(cache / "faiss_index"))
    (cache / "split_docs.json").write_text(json.dumps([
        {"page_content": d.page_content, "metadata": d.metadata} for d in docs
    ]), encoding="utf-8")
    manifest = build_index_manifest(
        knowledge_dir=corpus, docs_index_path=cache / "split_docs.json", faiss_dir=cache / "faiss_index",
        embedding={"provider": "openai", "model": "fixture", "dimensions": 2, "faiss_dimension": 2},
        chunk_size=520, chunk_overlap=80, chunk_count=1, vector_count=1,
    )
    assert save_index_manifest(cache / "index_manifest.json", manifest)
    settings = SimpleNamespace(rag_embedding_provider="openai", rag_embedding_model_name="fixture",
                               rag_embedding_dimensions=2, rag_chunk_size=520, rag_chunk_overlap=80)
    transfer.seal(cache, corpus, settings)
    return cache, corpus, settings


def test_transfer_installs_and_normalizes_paths_preserving_ids(bundle, tmp_path):
    cache, corpus, settings = bundle
    target = tmp_path / "knowledge"
    target.mkdir()
    (target / "old.txt").write_text("previous", encoding="utf-8")
    transfer.install(cache, corpus, target, settings)
    manifest, docs, store = transfer.verify(target, corpus, settings)
    assert manifest.knowledge_dir == str(corpus.resolve())
    assert manifest.docs_index_path == str(target / "split_docs.json")
    assert docs[0]["metadata"] == {"source_path": "folder/doc.md", "chunk_id": "stable-id"}
    assert store.index.ntotal == manifest.vector_count == 1
    assert list(tmp_path.glob("knowledge-backup-*/old.txt"))


def test_corrupt_index_rejected_before_pickle_load(bundle, monkeypatch):
    cache, corpus, settings = bundle
    (cache / "faiss_index/index.pkl").write_bytes(b"untrusted bytes")
    monkeypatch.setattr(FAISS, "load_local", lambda *a, **kw: pytest.fail("must not unpickle"))
    with pytest.raises(ValueError, match="digest"):
        transfer.verify(cache, corpus, settings)


def test_changed_corpus_rejected(bundle):
    cache, corpus, settings = bundle
    (corpus / "folder/doc.md").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="corpus"):
        transfer.verify(cache, corpus, settings)


def test_package_difference_rejected(bundle, monkeypatch):
    cache, corpus, settings = bundle
    monkeypatch.setattr(transfer, "packages", lambda: {"faiss-cpu": "incompatible"})
    with pytest.raises(ValueError, match="versions"):
        transfer.verify(cache, corpus, settings)


def test_wrong_dimensions_rejected(bundle):
    cache, corpus, settings = bundle
    settings.rag_embedding_dimensions = 3
    with pytest.raises(ValueError, match="stale"):
        transfer.verify(cache, corpus, settings)


def test_install_failure_preserves_destination(bundle, tmp_path):
    cache, corpus, settings = bundle
    target = tmp_path / "knowledge"
    target.mkdir()
    (target / "old.txt").write_text("previous", encoding="utf-8")
    (cache / "split_docs.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        transfer.install(cache, corpus, target, settings)
    assert (target / "old.txt").read_text() == "previous"


def test_trust_flag_required_before_any_deserialization(monkeypatch):
    monkeypatch.setattr("sys.argv", ["transfer", "verify", "--cache-dir", "fixture", "--knowledge-dir", "public"])
    with pytest.raises(SystemExit) as error:
        transfer.main()
    assert error.value.code == 2


def test_install_dry_run_never_publishes(bundle, monkeypatch, tmp_path):
    cache, corpus, settings = bundle
    settings.rag_index_manifest_path = ""
    target = tmp_path / "must-not-exist"
    monkeypatch.setattr(transfer, "Settings", lambda: settings)
    monkeypatch.setattr("sys.argv", ["transfer", "install", "--cache-dir", str(cache), "--knowledge-dir", str(corpus),
                                   "--target-dir", str(target), "--trusted-local-cache"])
    assert transfer.main() == 0
    assert not target.exists()
