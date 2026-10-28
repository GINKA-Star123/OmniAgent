from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_huggingface import HuggingFaceEmbeddings
from openai import OpenAI

logger = logging.getLogger(__name__)


class EmbeddingValidationError(ValueError):
    """A stable failure code and structural metadata, never the submitted text or vector values."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class OpenAICompatibleEmbeddings(Embeddings):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        batch_size: int = 64,
        dimensions: int | None = None,
    ) -> None:
        self.model = model
        self.batch_size = max(batch_size, 1)
        self.dimensions = dimensions
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        total_batches = (len(texts) + self.batch_size - 1) // self.batch_size
        for batch_number, batch in enumerate(self._batches(texts, self.batch_size), start=1):
            logger.info("Embedding batch started: batch=%s/%s items=%s", batch_number, total_batches, len(batch))
            try:
                embeddings.extend(self._embed_batch(batch))
            except EmbeddingValidationError as exc:
                exc.details.update(batch_number=batch_number, total_batches=total_batches)
                raise
            logger.info("Embedding batch completed: batch=%s/%s", batch_number, total_batches)
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text])[0]

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        cleaned = [text.replace("\n", " ").strip() for text in texts]
        kwargs = {
            "model": self.model,
            "input": cleaned,
            "encoding_format": "float",
        }
        if self.dimensions is not None:
            kwargs["dimensions"] = self.dimensions

        # Keep response types intact for validation before passing data into native FAISS.
        # In particular, SDK model coercion can turn a boolean into an accepted float.
        try:
            response = self.client.embeddings.with_raw_response.create(**kwargs)
        except ValueError as exc:
            raise EmbeddingValidationError(
                "embedding_request_value_error", "Embedding SDK rejected the request or response before JSON validation",
                validation_stage="request", expected_count=len(texts), expected_dimensions=self.dimensions,
            ) from exc
        try:
            payload = json.loads(response.content)
        except ValueError as exc:
            raise EmbeddingValidationError(
                "embedding_response_invalid_json", "Embedding response is not valid JSON",
                validation_stage="response_json", expected_count=len(texts), expected_dimensions=self.dimensions,
            ) from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        details = {
            "validation_stage": "response_validation",
            "expected_count": len(texts),
            "actual_count": len(data) if isinstance(data, list) else None,
            "data_type": type(data).__name__,
            "expected_dimensions": self.dimensions,
        }
        if not isinstance(data, list) or len(data) != len(texts):
            raise EmbeddingValidationError("embedding_response_count_mismatch",
                                           "Embedding response count does not match request count", **details)
        if any(not isinstance(item, dict) or type(item.get("index")) is not int for item in data):
            raise EmbeddingValidationError("embedding_response_index_type",
                                           "Embedding response indexes must be integers", **details)
        items = sorted(data, key=lambda item: item["index"])
        if [item["index"] for item in items] != list(range(len(texts))):
            raise EmbeddingValidationError("embedding_response_index_mismatch",
                                           "Embedding response indexes must be unique and contiguous",
                                           actual_indexes=[item["index"] for item in items[:64]], **details)
        vectors = [item.get("embedding") for item in items]
        dimension = self.dimensions
        for position, vector in enumerate(vectors):
            vector_details = {**details, "item_position": position, "vector_type": type(vector).__name__,
                              "actual_dimensions": len(vector) if isinstance(vector, list) else None}
            if not isinstance(vector, list) or not vector:
                raise EmbeddingValidationError("embedding_response_vector_type",
                                               "Embedding response dimension requires a nonempty numeric list", **vector_details)
            dimension = dimension or len(vector)
            if len(vector) != dimension:
                raise EmbeddingValidationError("embedding_response_dimension_mismatch",
                                               "Embedding response dimension does not match configuration", **vector_details)
            if any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) for value in vector):
                raise EmbeddingValidationError("embedding_response_nonfinite_or_nonnumeric",
                                               "Embedding response must contain finite numeric vectors", **vector_details)
        return vectors

    def _batches(self, items: list[str], size: int) -> Iterable[list[str]]:
        for index in range(0, len(items), size):
            yield items[index : index + size]


class LangChainVectorStore:
    def __init__(
        self,
        embedding_model_name: str,
        embedding_model_path: str = "",
        device: str = "cpu",
        normalize_embeddings: bool = True,
        local_files_only: bool = True,
        embedding_provider: str = "huggingface",
        embedding_api_key: str | None = None,
        embedding_base_url: str | None = None,
        embedding_batch_size: int = 64,
        embedding_dimensions: int | None = None,
    ) -> None:
        self.embedding_provider = embedding_provider.strip().lower()
        self.embedding_model_name = embedding_model_name.strip()
        self.embedding_model_path = embedding_model_path.strip()
        self.embedding_dimensions = embedding_dimensions
        self.embeddings = self._build_embeddings(
            embedding_model_name=embedding_model_name,
            embedding_model_path=embedding_model_path,
            device=device,
            normalize_embeddings=normalize_embeddings,
            local_files_only=local_files_only,
            embedding_api_key=embedding_api_key,
            embedding_base_url=embedding_base_url,
            embedding_batch_size=embedding_batch_size,
            embedding_dimensions=embedding_dimensions,
        )
        self.store: FAISS | None = None

    def build(self, documents: list[Document]) -> None:
        if not documents:
            raise ValueError("Cannot build vector store from empty documents")

        logger.info("Vector store build started: documents=%s", len(documents))
        self.store = FAISS.from_documents(documents, self.embeddings)
        logger.info("Vector store build completed: vectors=%s dimension=%s", self.count(), self.index_dimension())

    def save(self, directory: str | Path) -> None:
        if self.store is None:
            raise RuntimeError("Vector store is not built yet")

        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        self.store.save_local(str(path))

    def load(self, directory: str | Path) -> None:
        path = Path(directory)
        if not path.exists():
            raise FileNotFoundError(f"Vector store directory not found: {path}")

        self.store = FAISS.load_local(
            str(path),
            self.embeddings,
            allow_dangerous_deserialization=True,
        )

        index_dimension = self.index_dimension()
        if (
            self.embedding_dimensions
            and index_dimension
            and int(self.embedding_dimensions) != int(index_dimension)
        ):
            logger.warning(
                "FAISS index dimension (%s) does not match configured embedding dimension (%s). "
                "The index must be rebuilt.",
                index_dimension,
                self.embedding_dimensions,
            )

    def similarity_search(self, query: str, k: int = 6) -> list[Document]:

        if self.store is None:
            raise RuntimeError("Vector store is not loaded")

        return self.store.similarity_search(query, k=k)

    def similarity_search_with_score(self, query: str, k: int = 6) -> list[tuple[Document, float]]:
        if self.store is None:
            raise RuntimeError("Vector store is not loaded")

        raw_results = self.store.similarity_search_with_score(query, k=k)
        results: list[tuple[Document, float]] = []

        for doc, distance in raw_results:
            results.append((doc, self._distance_to_similarity(float(distance))))

        return results

    def count(self) -> int:
        if self.store is None:
            return 0

        return self.store.index.ntotal

    def index_dimension(self) -> int | None:
        """返回磁盘上 FAISS 索引的真实向量维度；未加载时返回 None"""
        if self.store is None:
            return None

        try:
            return int(self.store.index.d)
        except Exception:
            return None

    def identity(self) -> dict[str, Any]:
        """索引身份快照，写进索引清单，用于后续"配置变了没有"的比对。"""

        return {
            "provider": self.embedding_provider,
            "model": self.embedding_model_name,
            "model_path": self.embedding_model_path,
            "dimensions": self.embedding_dimensions,
            "faiss_dimension": self.index_dimension(),
            "vector_count": self.count(),
        }

    def _build_embeddings(
        self,
        embedding_model_name: str,
        embedding_model_path: str,
        device: str,
        normalize_embeddings: bool,
        local_files_only: bool,
        embedding_api_key: str | None,
        embedding_base_url: str | None,
        embedding_batch_size: int,
        embedding_dimensions: int | None,
    ) -> Embeddings:
        if self.embedding_provider in {"huggingface", "local"}:
            return self._build_huggingface_embeddings(
                embedding_model_name=embedding_model_name,
                embedding_model_path=embedding_model_path,
                device=device,
                normalize_embeddings=normalize_embeddings,
                local_files_only=local_files_only,
            )

        if self.embedding_provider in {"openai", "siliconflow"}:
            api_key = (embedding_api_key or "").strip()
            if not api_key:
                raise RuntimeError("RAG embedding API key is not configured.")

            if self.embedding_provider == "siliconflow":
                base_url = embedding_base_url or "https://api.siliconflow.cn/v1"
            else:
                base_url = embedding_base_url or "https://api.openai.com/v1"

            self._extend_no_proxy(base_url)

            logger.info(
                "Loading RAG API embedding: provider=%s model=%s base_url=%s batch_size=%s",
                self.embedding_provider,
                embedding_model_name,
                base_url,
                embedding_batch_size,
            )

            return OpenAICompatibleEmbeddings(
                model=embedding_model_name,
                api_key=api_key,
                base_url=base_url,
                batch_size=embedding_batch_size,
                dimensions=embedding_dimensions,
            )

        raise ValueError(f"Unsupported RAG embedding provider: {self.embedding_provider}")

    def _build_huggingface_embeddings(
        self,
        embedding_model_name: str,
        embedding_model_path: str,
        device: str,
        normalize_embeddings: bool,
        local_files_only: bool,
    ) -> HuggingFaceEmbeddings:
        model_name = self._resolve_model_name(
            embedding_model_name=embedding_model_name,
            embedding_model_path=embedding_model_path,
        )

        model_kwargs = {
            "device": device,
            "local_files_only": local_files_only,
        }

        encode_kwargs = {
            "normalize_embeddings": normalize_embeddings,
        }

        logger.info(
            "Loading RAG local embedding model: model=%s device=%s local_files_only=%s",
            model_name,
            device,
            local_files_only,
        )

        return HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs=model_kwargs,
            encode_kwargs=encode_kwargs,
        )

    def _resolve_model_name(
        self,
        embedding_model_name: str,
        embedding_model_path: str,
    ) -> str:
        local_path = embedding_model_path.strip()
        remote_name = embedding_model_name.strip()

        if local_path:
            path = Path(local_path)
            if not path.exists():
                raise FileNotFoundError(
                    f"RAG_EMBEDDING_MODEL_PATH does not exist: {path}. "
                    "Please download the embedding model locally first."
                )

            required_files = ["config.json"]
            missing = [name for name in required_files if not (path / name).exists()]
            if missing:
                raise FileNotFoundError(
                    f"Invalid local embedding model directory: {path}. "
                    f"Missing files: {missing}"
                )

            return str(path)

        if remote_name:
            return remote_name

        raise ValueError("RAG embedding model name or local path must be provided")

    def _distance_to_similarity(self, distance: float) -> float:
        score = 1.0 - distance / 2.0

        if score < 0.0:
            return 0.0
        if score > 1.0:
            return 1.0
        return score

    def _extend_no_proxy(self, url: str | None) -> None:
        if not url:
            return

        host = urlparse(url).hostname
        if not host:
            return

        existing = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
        items = [item.strip() for item in existing.split(",") if item.strip()]
        if host not in items:
            items.append(host)

        value = ",".join(items)
        os.environ["NO_PROXY"] = value
        os.environ["no_proxy"] = value
