from __future__ import annotations

import pytest

from aiagent.knowledge.reranker import SimpleReranker
from aiagent.knowledge.retriever import RetrievedChunk


def _chunk(key, text, rank):
    return RetrievedChunk(
        chunk_id=key, doc_id=key, title=key, source_path=key + ".txt",
        content=text, score=1 / (60 + rank), bm25_rank=rank,
        retrieval_sources=["bm25"],
    )


@pytest.mark.parametrize("alias", ["DL", "9z", "幽幽", "π姐", "ランちゃん", "梦の蝶"])
def test_specific_alias_beats_shared_profile_fields(alias):
    chunks = [
        _chunk("unrelated", "基本资料：生日、诞生祭、生贺曲、角色资料。", 1),
        _chunk("other", "生日：1月1日。基本资料与设定。", 2),
        _chunk("target", f"别称：{alias}。生日：9月17日。", 5),
    ]

    rows = SimpleReranker().rerank(
        query=f"我最近在看{alias}的资料，想问一下生日是几月几日呀？ 生日 诞生祭 生贺曲",
        chunks=chunks, top_k=3,
    )

    assert rows[0].chunk_id == "target"
    assert chunks[0].score == 1 / 61


def test_reranker_handles_no_shared_terms_and_empty_candidates():
    reranker = SimpleReranker()
    assert reranker.rerank(query="zzunknown", chunks=[], top_k=3) == []
    chunks = [_chunk("reference", "birthday reference", 1)]
    assert reranker.rerank(query="zzunknown", chunks=chunks)[0].chunk_id == "reference"


@pytest.mark.parametrize(("query", "content", "expected"), [
    ("starlight是谁", "别称：starlight_alt", False),
    ("starlight_alt是谁", "别称：starlight", False),
    ("DL的声源", "**别称**：[DL](https://example.invalid)", True),
    ("DL的声源", "DL只是文中提到的另一个歌手。", False),
    ("星星是谁", "别称：星", False),
])
def test_alias_boost_requires_explicit_field_and_safe_boundaries(query, content, expected):
    assert SimpleReranker._has_explicit_alias_match(query.lower(), content) is expected
