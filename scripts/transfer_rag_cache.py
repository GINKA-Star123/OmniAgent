"""Seal, verify and install a trusted local CPU FAISS cache without network requests."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import tempfile
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import Embeddings

from aiagent.knowledge.document_loader import DocumentLoader
from aiagent.knowledge.index_manifest import (
    evaluate_index_freshness,
    fingerprint_knowledge_files,
    load_index_manifest,
    save_index_manifest,
)
from config.settings import Settings
from scripts.rebuild_rag_cache import emit, publish, safe_failure

FILES = ("split_docs.json", "index_manifest.json", "faiss_index/index.faiss", "faiss_index/index.pkl")
PACKAGES = ("faiss-cpu", "numpy", "langchain-community", "langchain-core")


class OfflineEmbeddings(Embeddings):
    def embed_documents(self, texts):
        raise RuntimeError("Cache transfer must never request embeddings")

    def embed_query(self, text):
        raise RuntimeError("Cache transfer must never request embeddings")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def corpus_hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p.suffix.lower() in DocumentLoader.SUPPORTED_SUFFIXES}


def packages() -> dict[str, str]:
    return {name: importlib.metadata.version(name) for name in PACKAGES}


def file_hashes(cache: Path) -> dict[str, str]:
    for name in FILES:
        path = cache / name
        if not path.is_file() or path.is_symlink() or cache.resolve() not in path.resolve().parents:
            raise ValueError("Cache is incomplete or contains linked index files")
    return {name: digest(cache / name) for name in FILES}


def check_cache(cache: Path, knowledge: Path, settings):
    """Caller must trust the pickle; digests prove integrity, not provenance."""
    import numpy as np

    manifest = load_index_manifest(cache / "index_manifest.json")
    store = FAISS.load_local(str(cache / "faiss_index"), OfflineEmbeddings(),
                             allow_dangerous_deserialization=True)
    docs = json.loads((cache / "split_docs.json").read_text(encoding="utf-8"))
    if manifest is None or not docs or len(docs) != store.index.ntotal:
        raise ValueError("Manifest, document and vector counts must agree")
    if manifest.chunk_count != len(docs) or manifest.vector_count != len(docs):
        raise ValueError("Manifest counts do not match the actual cache")
    if manifest.faiss_dimension != store.index.d or manifest.embedding_dimensions != store.index.d:
        raise ValueError("Manifest dimension does not match the actual FAISS index")
    if set(store.index_to_docstore_id) != set(range(len(docs))):
        raise ValueError("FAISS document mapping is incomplete")
    for i, doc in enumerate(docs):
        saved = store.docstore.search(store.index_to_docstore_id[i])
        if saved.page_content != doc["page_content"] or saved.metadata != doc["metadata"]:
            raise ValueError("JSON and FAISS document order or content differ")
    # Exercise native reconstruction and search, without invoking embed_query.
    vectors = store.index.reconstruct_n(0, store.index.ntotal)
    if not np.isfinite(vectors).all():
        raise ValueError("FAISS contains nonfinite vectors")
    distances, _ = store.index.search(vectors[:1], 1)
    if not np.isfinite(distances).all() or abs(float(distances[0, 0])) > 1e-4:
        raise ValueError("FAISS self-search verification failed")
    freshness = evaluate_index_freshness(
        manifest=manifest, manifest_path=cache / "index_manifest.json", knowledge_dir=knowledge,
        embedding={"provider": settings.rag_embedding_provider, "model": settings.rag_embedding_model_name,
                   "dimensions": settings.rag_embedding_dimensions, "faiss_dimension": store.index.d},
        chunk_size=settings.rag_chunk_size, chunk_overlap=settings.rag_chunk_overlap,
    )
    if not freshness.ok or freshness.stale or freshness.status != "fresh":
        raise ValueError("Cache configuration or corpus is stale: " + ",".join(freshness.reasons))
    return manifest, docs, store


def seal(cache: Path, knowledge: Path, settings) -> None:
    check_cache(cache, knowledge, settings)
    payload = {"schema_version": 1, "files": file_hashes(cache),
               "corpus": corpus_hashes(knowledge), "packages": packages()}
    (cache / "transfer_manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    emit(stage="sealed", cache=cache, network=False, files=len(FILES), corpus_files=len(payload["corpus"]))


def verify(cache: Path, knowledge: Path, settings):
    payload = json.loads((cache / "transfer_manifest.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("files") != file_hashes(cache):
        raise ValueError("Transfer manifest or cache digest mismatch")
    if not payload.get("corpus") or payload["corpus"] != corpus_hashes(knowledge):
        raise ValueError("Source and destination corpus bytes differ")
    if payload.get("packages") != packages():
        raise ValueError("FAISS/numpy/LangChain package versions differ; verify compatibility first")
    return check_cache(cache, knowledge, settings)


def install(cache: Path, knowledge: Path, target: Path, settings) -> None:
    source = cache.resolve()
    destination = target.resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Transfer source and destination must not overlap")
    if knowledge.resolve() == destination or destination in knowledge.resolve().parents or knowledge.resolve() in destination.parents:
        raise ValueError("Destination must not overlap the corpus")
    if target.is_symlink():
        raise ValueError("Destination must not be a symlink")
    verify(cache, knowledge, settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".knowledge-import-", dir=target.parent))
    for name in (*FILES, "transfer_manifest.json"):
        output = staging / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache / name, output)
    manifest, docs, store = verify(staging, knowledge, settings)
    # Normalize relative metadata on both sides; retain every document ID and vector row.
    for i, doc in enumerate(docs):
        path = str(doc["metadata"].get("source_path", "")).replace("\\", "/")
        if path.startswith("/") or ":" in path or ".." in path.split("/"):
            raise ValueError("Cache source paths must be corpus-relative")
        doc["metadata"]["source_path"] = path
        store.docstore.search(store.index_to_docstore_id[i]).metadata["source_path"] = path
    (staging / "split_docs.json").write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")
    store.save_local(str(staging / "faiss_index"))
    manifest = manifest.model_copy(update={
        "knowledge_dir": str(knowledge.resolve()), "docs_index_path": str(destination / "split_docs.json"),
        "faiss_dir": str(destination / "faiss_index"), "files": fingerprint_knowledge_files(knowledge),
    })
    if not save_index_manifest(staging / "index_manifest.json", manifest):
        raise RuntimeError("Cannot save relocated manifest")
    seal(staging, knowledge, settings)
    verify(staging, knowledge, settings)
    backup = publish(staging, target)
    emit(stage="installed", cache=target, backup=backup, vectors=len(docs), dimensions=store.index.d,
         freshness="fresh", network=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seal", "verify", "install"))
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--knowledge-dir", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path)
    parser.add_argument("--trusted-local-cache", action="store_true", help="Accept only your own trusted FAISS pickle")
    parser.add_argument("--execute", action="store_true", help="Allow install to replace the target, preserving a backup")
    args = parser.parse_args()
    if not args.trusted_local_cache:
        parser.error("Explicit --trusted-local-cache is required before deserialization")
    if args.action == "install" and args.target_dir is None:
        parser.error("install requires --target-dir")
    try:
        settings = Settings()
        if settings.rag_index_manifest_path and Path(settings.rag_index_manifest_path).name != "index_manifest.json":
            raise ValueError("Transfer currently requires the default index_manifest.json path")
        if args.action == "seal":
            seal(args.cache_dir, args.knowledge_dir, settings)
        elif args.action == "verify":
            manifest, _, _ = verify(args.cache_dir, args.knowledge_dir, settings)
            emit(stage="verified", vectors=manifest.vector_count, dimensions=manifest.faiss_dimension, network=False)
        elif not args.execute:
            verify(args.cache_dir, args.knowledge_dir, settings)
            emit(stage="install_plan", target=args.target_dir, network=False, execute=False)
        else:
            install(args.cache_dir, args.knowledge_dir, args.target_dir, settings)
    except Exception as exc:
        emit(**safe_failure(exc))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
