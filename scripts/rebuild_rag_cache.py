"""Plan a staged RAG rebuild; only --execute permits provider requests."""

from __future__ import annotations

import argparse
import faulthandler
import json
import logging
import subprocess
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from config.env_secrets import resolve_named_secret
from config.paths import KNOWLEDGE_CACHE_DIR, KNOWLEDGE_INDEX_MANIFEST_NAME, KNOWLEDGE_PUBLIC_DIR
from config.settings import Settings


def emit(**values) -> None:
    print(json.dumps(values, ensure_ascii=False, default=str), flush=True)


def manifest_relative_path(settings) -> Path:
    cache = KNOWLEDGE_CACHE_DIR.resolve()
    manifest = Path(settings.rag_index_manifest_path).resolve() if settings.rag_index_manifest_path else (
        cache / KNOWLEDGE_INDEX_MANIFEST_NAME
    )
    try:
        relative = manifest.relative_to(cache)
    except ValueError as exc:
        raise ValueError("Rebuild requires a manifest inside the knowledge cache directory") from exc
    if not relative.parts or relative.parts[0] in {"split_docs.json", "faiss_index"}:
        raise ValueError("Manifest path overlaps reserved index files")
    return relative


def preflight(dimensions: int = 4096) -> None:
    """Exercise the SDK/JSON/FAISS path with synthetic vectors and no network."""
    import httpx
    from langchain_core.documents import Document
    from openai import OpenAI

    from aiagent.knowledge.vector_store import LangChainVectorStore

    dimension = dimensions or 4096
    if dimension < 1:
        raise ValueError("Embedding dimension must be positive")

    def respond(request):
        body = json.loads(request.content)
        # The first coordinate encodes a stable nearest neighbour for the reload check.
        data = [{"object": "embedding", "index": i,
                 "embedding": [float(text == "fixture-b"), *[0.03125] * (dimension - 1)]}
                for i, text in enumerate(body["input"])]
        return httpx.Response(200, json={"object": "list", "data": data, "model": "offline-fixture",
                                        "usage": {"prompt_tokens": 0, "total_tokens": 0}})

    emit(stage="preflight_start", dimensions=dimension, network=False)
    store = LangChainVectorStore(
        "offline-fixture", embedding_provider="openai", embedding_api_key="offline-placeholder",
        embedding_base_url="https://offline.invalid/v1", embedding_dimensions=dimension,
    )
    store.embeddings.client.close()
    with OpenAI(api_key="offline-placeholder", base_url="https://offline.invalid/v1", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
        store.embeddings.client = client
        store.build([Document(page_content="fixture-a"), Document(page_content="fixture-b")])
        with tempfile.TemporaryDirectory(prefix="aiagent-faiss-preflight-") as directory:
            store.save(directory)
            store.load(directory)  # Only deserialize the index created above, never an untrusted pickle.
            matches = store.similarity_search("fixture-b", k=1)
            if store.count() != 2 or store.index_dimension() != dimension or matches[0].page_content != "fixture-b":
                raise RuntimeError("Native index preflight verification failed")
    emit(stage="preflight_passed", dimensions=dimension, network=False,
         faiss_backend=type(store.store.index).__module__)


def publish(staging: Path, cache: Path) -> Path | None:
    """Two renames with rollback; callers must stop all other readers/writers first."""
    backup = None
    if cache.exists():
        suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        backup = cache.with_name(f"knowledge-backup-{suffix}")
        cache.rename(backup)
        emit(stage="previous_cache_preserved", backup=backup)
    try:
        staging.rename(cache)
    except OSError:
        if backup is not None and not cache.exists():
            backup.rename(cache)
        raise
    return backup


def configured_vector_store(settings):
    from aiagent.knowledge.vector_store import LangChainVectorStore

    provider = settings.rag_embedding_provider.strip().lower()
    api_key = resolve_named_secret(settings.rag_embedding_api_key_env or "")
    if provider in {"openai", "siliconflow"} and not api_key:
        raise ValueError("RAG embedding named API key is missing")
    base_url = settings.rag_embedding_base_url or (
        settings.siliconflow_base_url if provider == "siliconflow" else None
    )
    if provider in {"openai", "siliconflow"} and not (base_url or "").startswith(("https://", "http://")):
        raise ValueError("RAG embedding base URL must be a literal HTTP(S) URL")
    return LangChainVectorStore(
        embedding_model_name=settings.rag_embedding_model_name,
        embedding_model_path=settings.rag_embedding_model_path,
        device=settings.rag_embedding_device,
        local_files_only=settings.rag_embedding_local_files_only,
        embedding_provider=provider,
        embedding_api_key=api_key,
        embedding_base_url=base_url,
        embedding_batch_size=settings.rag_embedding_batch_size,
        embedding_dimensions=settings.rag_embedding_dimensions,
    )


def probe_provider(settings, items: int = 2) -> None:
    """One explicitly authorized provider request, synthetic text only; never publish a cache."""
    if not 1 <= items <= 32:
        raise ValueError("Provider probe items must be between 1 and 32")
    if settings.rag_embedding_provider.strip().lower() not in {"openai", "siliconflow"}:
        raise ValueError("Provider probe requires a remote embedding provider")
    store = configured_vector_store(settings)
    client = store.embeddings.client
    # Match the requested batch in a single HTTP call, even if normal configuration uses smaller batches.
    store.embeddings.batch_size = items
    emit(stage="provider_probe_start", items=items, request_budget=1, synthetic=True, cache_modified=False)
    try:
        with client.with_options(max_retries=0, timeout=30.0) as probe_client:
            store.embeddings.client = probe_client
            vectors = store.embeddings.embed_documents([f"Offline evaluation embedding probe {i}." for i in range(items)])
    finally:
        client.close()
    emit(stage="provider_probe_passed", items=len(vectors), dimensions=len(vectors[0]),
         synthetic=True, cache_modified=False)


def rebuild(settings) -> None:
    from aiagent.knowledge.document_loader import DocumentLoader
    from aiagent.knowledge.index_manifest import load_index_manifest, save_index_manifest
    from aiagent.knowledge.rag_pipeline import RAGPipeline
    from aiagent.knowledge.reranker import SimpleReranker
    from aiagent.knowledge.retriever import HybridRetriever

    manifest_relative = manifest_relative_path(settings)
    cache = KNOWLEDGE_CACHE_DIR.absolute()
    if cache.is_symlink():
        raise ValueError("Knowledge cache must not be a symlink")
    vector_store = configured_vector_store(settings)
    cache.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".knowledge-build-", dir=cache.parent))
    emit(stage="build_start", staging=staging, previous_cache_untouched=True)
    pipeline = RAGPipeline(
        loader=DocumentLoader(),
        retriever=HybridRetriever(bm25_top_k=settings.rag_bm25_top_k, vector_top_k=settings.rag_vector_top_k),
        vector_store=vector_store,
        reranker=SimpleReranker(),
        knowledge_dir=KNOWLEDGE_PUBLIC_DIR,
        docs_index_path=staging / "split_docs.json",
        faiss_dir=staging / "faiss_index",
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        final_top_k=settings.rag_final_top_k,
        manifest_path=staging / manifest_relative,
        auto_rebuild_on_stale=False,
    )
    pipeline.build_index(force_rebuild=True)
    emit(stage="verify_start", staging=staging)
    pipeline.vector_store.load(pipeline.faiss_dir)
    count = pipeline.vector_store.count()
    if not count or count != len(pipeline.documents):
        raise RuntimeError("Vector count does not match chunk count")
    manifest = load_index_manifest(pipeline.manifest_path)
    freshness = pipeline.index_freshness(force_refresh=True)
    if manifest is None or freshness.get("status") != "fresh" or not freshness.get("ok") or freshness.get("stale"):
        raise RuntimeError("Index manifest verification failed")
    manifest = manifest.model_copy(update={
        "docs_index_path": str(cache / "split_docs.json"), "faiss_dir": str(cache / "faiss_index"),
    })
    if not save_index_manifest(pipeline.manifest_path, manifest):
        raise RuntimeError("Cannot save verified index manifest")
    emit(stage="publish_start", cache_dir=cache)
    backup = publish(staging, cache)
    pipeline.docs_index_path = cache / "split_docs.json"
    pipeline.faiss_dir = cache / "faiss_index"
    pipeline.manifest_path = cache / manifest_relative
    freshness = pipeline.index_freshness(force_refresh=True)
    emit(stage="complete", backup=backup, stats=pipeline.stats(), freshness=freshness)


def safe_failure(exc: Exception) -> dict:
    from openai import APIConnectionError, APITimeoutError

    from aiagent.knowledge.vector_store import EmbeddingValidationError

    result = {"stage": "failed", "error_code": "rebuild_error", "error_type": type(exc).__name__}
    if isinstance(exc, APITimeoutError):
        result["error_code"] = "embedding_provider_timeout"
    elif isinstance(exc, APIConnectionError):
        result["error_code"] = "embedding_provider_connection_error"
    if isinstance(exc, EmbeddingValidationError):
        result.update(error_code=exc.code, message=str(exc), diagnostics=exc.details)
    status = getattr(exc, "status_code", None)
    if type(status) is int:
        result.update(error_code="embedding_provider_http_error", http_status=status)
    # Do not print exception text, source lines, frame locals, request bodies, headers or response bodies.
    result["error_locations"] = [
        {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
        for frame in traceback.extract_tb(exc.__traceback__)[-8:]
    ]
    if exc.__cause__ is not None:
        result["cause_type"] = type(exc.__cause__).__name__
        result["cause_locations"] = [
            {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(exc.__cause__.__traceback__)[-8:]
        ]
    return result


def run_worker(mode: str, probe_items: int = 2) -> int:
    command = [sys.executable, "-X", "faulthandler", "-u", "-m", "scripts.rebuild_rag_cache", "--_worker", mode]
    command.extend(["--cache-dir", str(KNOWLEDGE_CACHE_DIR), "--knowledge-dir", str(KNOWLEDGE_PUBLIC_DIR)])
    if mode in {"build", "probe"}:
        command.append("--execute")
    if mode == "probe":
        command.extend(["--probe-items", str(probe_items)])
    result = subprocess.run(command, check=False)
    if result.returncode:
        emit(stage="worker_failed", worker=mode, exit_code=result.returncode,
             error_code="native_crash" if result.returncode < 0 else "worker_error",
             hint="Do not retry paid rebuilds blindly. Preserve stderr and staging; previous cache is retained.")
        return 2
    return 0


def main() -> int:
    global KNOWLEDGE_CACHE_DIR, KNOWLEDGE_PUBLIC_DIR
    faulthandler.enable(file=sys.__stderr__)
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--execute", action="store_true", help="Run offline preflight, then build and publish")
    action.add_argument("--preflight", action="store_true", help="Only test SDK and native FAISS offline")
    parser.add_argument("--probe-provider", action="store_true", help="With --execute: only one synthetic provider request, no rebuild")
    parser.add_argument("--probe-items", type=int, default=2, help="Synthetic inputs in the single probe request (1..32)")
    parser.add_argument("--_worker", choices=("preflight", "build", "probe"), help=argparse.SUPPRESS)
    parser.add_argument("--cache-dir", type=Path, help="Independent output cache; defaults to the project cache")
    parser.add_argument("--knowledge-dir", type=Path, help="Source corpus; defaults to project public knowledge")
    args = parser.parse_args()
    if args.cache_dir:
        KNOWLEDGE_CACHE_DIR = args.cache_dir.absolute()
    if args.knowledge_dir:
        KNOWLEDGE_PUBLIC_DIR = args.knowledge_dir.absolute()
    if KNOWLEDGE_CACHE_DIR.resolve() == KNOWLEDGE_PUBLIC_DIR.resolve() or (
        KNOWLEDGE_CACHE_DIR.resolve() in KNOWLEDGE_PUBLIC_DIR.resolve().parents
        or KNOWLEDGE_PUBLIC_DIR.resolve() in KNOWLEDGE_CACHE_DIR.resolve().parents
    ):
        parser.error("Cache and corpus directories must not overlap")
    if args.probe_provider and args.preflight:
        parser.error("--probe-provider cannot be combined with --preflight")
    if not 1 <= args.probe_items <= 32:
        parser.error("--probe-items must be between 1 and 32")
    if args.probe_items != 2 and not (args.probe_provider or args._worker == "probe"):
        parser.error("--probe-items requires --probe-provider")
    settings = Settings()
    if args._worker:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        # Missing optional SIMD wrappers are normal when the unified FAISS module loads successfully.
        logging.getLogger("faiss.loader").setLevel(logging.WARNING)
        try:
            if args._worker == "preflight":
                preflight(settings.rag_embedding_dimensions or 4096)
            elif args._worker == "probe" and args.execute:
                probe_provider(settings, args.probe_items)
            elif args._worker == "build" and args.execute:
                rebuild(settings)
            else:
                raise ValueError("Build worker requires --execute")
        except Exception as exc:
            emit(**safe_failure(exc))
            return 2
        return 0
    emit(execute=args.execute, preflight=args.preflight, probe_provider=args.probe_provider,
         probe_items=args.probe_items if args.probe_provider else None, knowledge_dir=str(KNOWLEDGE_PUBLIC_DIR),
         cache_dir=str(KNOWLEDGE_CACHE_DIR), provider=settings.rag_embedding_provider,
         model=settings.rag_embedding_model_name, dimensions=settings.rag_embedding_dimensions,
         python=sys.executable, python_version=sys.version.split()[0],
         note="Stop API and worker readers/writers before executing; remote embedding may be billed.")
    if not args.execute and not args.preflight:
        return 0
    if args.execute and not args.probe_provider:
        try:
            manifest_relative_path(settings)
        except ValueError:
            emit(stage="failed", error_code="manifest_path_outside_cache_or_reserved")
            return 2
    result = run_worker("preflight")
    if result or not args.execute:
        return result
    return run_worker("probe", args.probe_items) if args.probe_provider else run_worker("build")


if __name__ == "__main__":
    raise SystemExit(main())
