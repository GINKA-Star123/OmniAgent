from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def format_rag_chunk(chunk: dict[str, Any], index: int) -> str:
    source = str(chunk.get("source_path", "")).replace("\\", "/")
    source_name = PurePosixPath(source).name if source else "unknown"
    sources = chunk.get("retrieval_sources") or []
    source_text = ", ".join(str(item) for item in sources) if sources else "unknown"
    cosine = chunk.get("cosine_score")
    cosine_text = f"{cosine:.4f}" if isinstance(cosine, (int, float)) else "无"
    return (
        f"[知识片段 {index}]\n"
        f"标题: {chunk.get('title', '')}\n"
        f"来源: {source_name}\n"
        f"召回方式: {source_text}\n"
        f"BM25排名: {chunk.get('bm25_rank') if chunk.get('bm25_rank') is not None else '无'}\n"
        f"向量排名: {chunk.get('vector_rank') if chunk.get('vector_rank') is not None else '无'}\n"
        f"余弦相似度: {cosine_text}\n"
        f"内容:\n{str(chunk.get('content', '')).strip()}"
    )
