from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document

from aiagent.knowledge.query_normalizer import normalize_rag_query
from aiagent.knowledge.rag_pipeline import RAGPipeline
from aiagent.knowledge.reranker import SimpleReranker
from aiagent.knowledge.retriever import HybridRetriever, RetrievedChunk


def document(key, content):
    return Document(page_content=content, metadata={
        "chunk_id": key, "doc_id": key, "title": key, "file_name": key + ".md", "source_path": key + ".md",
    })


def test_raw_and_expanded_lexical_candidates_are_unioned_without_double_rrf_vote():
    raw = "角色生日活动"
    expanded = normalize_rag_query(raw)
    assert raw != expanded
    a, b, c = [document(key, "生日活动 生贺曲") for key in ("raw-only", "shared", "expanded-only")]
    retriever = HybridRetriever(bm25_top_k=2, vector_top_k=0)
    lexical = Mock()
    lexical.invoke.side_effect = lambda query: [a, b] if query == raw else [c, b]
    retriever.bm25_retriever = lexical
    vector = Mock()
    rows = retriever.retrieve(raw, vector, top_k=10)
    assert {r.chunk_id for r in rows} == {"raw-only", "shared", "expanded-only"}
    shared = next(r for r in rows if r.chunk_id == "shared")
    assert shared.bm25_rank == 2
    assert shared.score == pytest.approx(1 / 62)
    assert shared.retrieval_sources == ["bm25"]
    assert lexical.invoke.call_count == 2
    vector.similarity_search_with_score.assert_not_called()


def test_unchanged_query_uses_one_lexical_pass_and_one_raw_vector_query():
    retriever = HybridRetriever(vector_top_k=6)
    lexical = Mock()
    lexical.invoke.return_value = [document("target", "生日：9月6日")]
    retriever.bm25_retriever = lexical
    vector = Mock()
    vector.similarity_search_with_score.return_value = []
    query = "星桥生日是几月几日？"
    retriever.retrieve(query, vector)
    lexical.invoke.assert_called_once_with(query)
    vector.similarity_search_with_score.assert_called_once_with(query, k=6)


def test_expansion_never_enters_the_single_vector_request():
    retriever = HybridRetriever()
    vector = Mock()
    vector.similarity_search_with_score.return_value = []
    raw = "阿绫有哪些生日活动？"
    assert raw != normalize_rag_query(raw)
    assert retriever.retrieve(raw, vector) == []
    vector.similarity_search_with_score.assert_called_once_with(raw, k=8)


def test_blank_query_makes_no_retrieval_calls():
    vector = Mock()
    assert HybridRetriever().retrieve("   ", vector) == []
    vector.similarity_search_with_score.assert_not_called()


@pytest.mark.parametrize("name", ["猫尾++", "星桥", "starlight_alt", "梦の蝶"])
def test_named_birthday_profile_survives_hybrid_event_distractors(name):
    target = document(name, f"姓名：{name}\n生日：9月6日。身高：160cm。")
    noise = [document(f"noise-{i}", "生日：1月1日。生日活动、诞生祭、生贺曲。" * 12) for i in range(40)]
    retriever = HybridRetriever(bm25_top_k=6, vector_top_k=6)
    retriever.build([target, *noise])
    vector = Mock()
    vector.similarity_search_with_score.return_value = [(doc, 0.95) for doc in noise[:6]]
    pipeline = RAGPipeline(
        loader=Mock(), retriever=retriever, vector_store=vector, reranker=SimpleReranker(), final_top_k=3,
    )
    pipeline.documents = [target, *noise]
    query = f"{name}生日是几月几日？"
    rows = pipeline.retrieve(query, top_k=3)
    assert rows[0].source_path == f"{name}.md"
    assert "9月6日" in rows[0].content
    vector.similarity_search_with_score.assert_called_once_with(query, k=6)


@pytest.mark.parametrize("name,query,match", [
    ("猫尾+", "猫尾++生日", False), ("猫尾++", "猫尾++生日", True),
    ("starlight", "starlight_alt生日", False), ("starlight_alt", "starlight_alt生日", True),
    ("starlight_alt", "mystarlight_alt生日", False),
])
def test_profile_identity_preserves_compound_name_boundaries(name, query, match):
    chunk = RetrievedChunk(chunk_id="x", doc_id="x", title=name, source_path=f"nested/{name}.md", content="生日", score=0)
    assert SimpleReranker._has_profile_subject_match(query, chunk) is match


def test_music_request_does_not_prioritize_the_profile_file():
    profile = RetrievedChunk(chunk_id="profile", doc_id="a", title="星桥", source_path="星桥.md",
                             content="生日：9月6日。", score=0.02)
    song = RetrievedChunk(chunk_id="song", doc_id="b", title="生贺曲", source_path="song.md",
                          content="星桥的生贺曲。", score=0.10)
    rows = SimpleReranker().rerank("星桥有哪些生日歌曲？", [profile, song])
    assert rows[0].chunk_id == "song"


def test_runtime_passes_raw_query_to_retrieval_and_keeps_normalized_inspection():
    from apps.core.runtime import CoreRuntime

    pipeline = Mock()
    pipeline.inspect.return_value = {"query": normalize_rag_query("阿绫是谁"), "chunks": []}
    runtime = SimpleNamespace(rag_pipeline=pipeline)
    CoreRuntime.search_knowledge(runtime, "阿绫是谁", 3)
    CoreRuntime.get_knowledge_prompt_context(runtime, "阿绫是谁", 3)
    result = CoreRuntime.inspect_knowledge(runtime, "阿绫是谁", 3)
    pipeline.debug_retrieve.assert_called_once_with(query="阿绫是谁", top_k=3)
    pipeline.format_for_prompt.assert_called_once_with(query="阿绫是谁", top_k=3)
    pipeline.inspect.assert_called_once_with(query="阿绫是谁", top_k=3)
    assert "乐正绫" in result["query"]


def test_api_evaluation_sends_the_actual_user_question(monkeypatch, tmp_path):
    from aiagent.evaluation import adapters

    captured = []

    async def steps(raw_steps, cleanup, root, user):
        captured.extend(raw_steps)
        return [{"body": {"chunks": [], "should_inject": False}}]

    monkeypatch.setattr(adapters, "run_steps", steps)
    raw = "阿绫有哪些生日活动？"
    params = adapters.RAGInput(query=raw, backend="api", top_k=3)
    result = adapters.rag_observation(params, tmp_path, "eval-unit")
    assert captured[0]["body"]["query"] == raw
    assert result.scope == "isolated_api_retrieval"


def test_graph_retains_query_before_domain_expansion():
    from aiagent.graphs.rag_graph import RAGRunner

    runner = RAGRunner(Mock())
    query = runner._build_search_query("阿绫有哪些生日活动？", "阿绫生日活动", "活动")
    assert query == "阿绫生日活动 阿绫有哪些生日活动？ 活动"
    assert "生贺曲" not in query
