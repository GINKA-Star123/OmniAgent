from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document

from aiagent.knowledge.profile_fields import content_profile_fields, matched_profile_sources, query_profile_fields
from aiagent.knowledge.rag_pipeline import RAGPipeline
from aiagent.knowledge.reranker import SimpleReranker
from aiagent.knowledge.retriever import HybridRetriever


def document(key, source, content):
    return Document(page_content=content, metadata={
        "chunk_id": key, "doc_id": source, "source_path": source + ".md",
        "file_name": source + ".md", "title": source + " / 基本资料",
    })


@pytest.mark.parametrize("question,content,field", [
    ("生日是几月几日", "生日：9月6日", "birthday"),
    ("代表色是什么", "代表色：#abcdef", "color"),
    ("声源是谁", "- **声源**：某配音者", "voice"),
    ("不同版本的声源有哪些", "多位声源：甲、乙", "voice"),
    ("设定年龄是多少", "年龄：20", "age"),
    ("设定身高是多少", "身高：170cm", "height"),
    ("属于哪个团体", "所属团体：某团队", "group"),
    ("头发是什么颜色", "多种发色：蓝、白", "hair"),
    ("眼睛是什么颜色", "多种瞳色：白、蓝", "eyes"),
    ("音之精灵叫什么", "音之精灵：精灵甲", "spirit"),
    ("发布日期是什么时候", "发布日期：2023.7.4", "release"),
    ("别称有哪些", "别称：StarBridge", "alias"),
])
def test_named_field_survives_missing_lexical_and_misleading_vector_candidates(question, content, field):
    target = document("target", "星桥", content)
    noise = [document(f"noise-{i}", f"其他{i}", content) for i in range(6)]
    retriever = HybridRetriever(bm25_top_k=6, vector_top_k=6)
    retriever.build([*noise, target])
    lexical = Mock()
    lexical.invoke.return_value = noise
    retriever.bm25_retriever = lexical
    vector = Mock()
    vector.similarity_search_with_score.return_value = [(item, .99) for item in noise]
    pipeline = RAGPipeline(Mock(), retriever, vector, SimpleReranker())
    pipeline.documents = [*noise, target]
    query = "星桥" + question + "？"
    rows = pipeline.retrieve(query, top_k=1)
    assert rows[0].chunk_id == "target"
    assert rows[0].content == content
    assert query_profile_fields(query) == {field}
    assert content_profile_fields(content) == {field}
    assert rows[0].retrieval_sources == ["profile_field"]
    assert rows[0].bm25_rank is None and rows[0].vector_rank is None
    vector.similarity_search_with_score.assert_called_once_with(query, k=6)


@pytest.mark.parametrize("query", ["星桥生日歌曲有哪些", "给星桥写一段生日祝福", "星桥活动的发布日期",
                                  "设计一个年龄20岁的星桥", "星桥专辑代表色是什么", "所有角色谁最高"])
def test_creative_music_and_unscoped_queries_do_not_get_profile_lookup(query):
    assert not query_profile_fields(query)


@pytest.mark.parametrize("content", ["这是关于发色：蓝色的叙述。", "年龄：  ", "### 年龄", "代表色很漂亮。"])
def test_only_nonempty_explicit_fields_are_candidates(content):
    assert not content_profile_fields(content)


def test_empty_field_does_not_consume_the_next_line_as_its_value():
    assert content_profile_fields("年龄： \n身高：170cm") == {"height"}


@pytest.mark.parametrize("name,query,expected", [
    ("猫尾+", "猫尾++声源是谁", False), ("猫尾++", "猫尾++声源是谁", True),
    ("starlight", "starlight_alt设定年龄是多少", False),
    ("starlight_alt", "mystarlight_alt设定年龄是多少", False),
    ("starlight_alt", "starlight_alt设定年龄是多少", True),
    ("D-Lin", "D-Lin发布日期是什么时候", True),
    ("岚", "岚设定年龄是多少", True), ("岚", "请问岚的声源是谁", True),
    ("岚", "按《岚》的基本资料，身高是多少", True),
    ("岚", "春岚声源是谁", False), ("岚", "岚风声源是谁", False),
])
def test_compound_subject_boundaries(name, query, expected):
    source = name + ".md"
    assert (source in matched_profile_sources(query, [source])) is expected


def test_longest_direct_subject_wins_over_substrings_and_expanded_metadata():
    assert matched_profile_sources("夏语遥设定年龄是多少", ["夏语.md", "夏语遥.md"]) == {"夏语遥.md"}
    assert matched_profile_sources("洛天依声源是谁", ["天依.md", "洛天依.md"]) == {"洛天依.md"}
    # A directly named derivative is not replaced by an inferred canonical character.
    assert matched_profile_sources("徵谣设定年龄是多少", ["徵谣.md", "徵羽摩柯.md"]) == {"徵谣.md"}
    assert matched_profile_sources("阿绫声源是谁", ["乐正绫.md"]) == {"乐正绫.md"}


def test_named_source_without_requested_field_is_not_fabricated():
    retriever = HybridRetriever(vector_top_k=0)
    retriever.build([document("wrong-field", "星桥", "身高：170cm")])
    retriever.bm25_retriever = None
    assert retriever.retrieve("星桥声源是谁", Mock()) == []


def test_field_marker_does_not_invent_extra_rrf_votes_or_drop_real_rank():
    target = document("target", "星桥", "声源：未知")
    retriever = HybridRetriever(vector_top_k=0)
    retriever.build([target])
    rows = retriever.retrieve("星桥声源是谁", Mock())
    assert rows[0].bm25_rank == 1
    assert rows[0].retrieval_sources == ["bm25", "profile_field"]
    assert rows[0].score == pytest.approx(1 / 61)
    assert rows[0].content == "声源：未知"


@pytest.mark.parametrize("with_vector_distractors", [False, True])
def test_full_current_corpus_regression_without_remote_embedding(with_vector_distractors):
    root = Path(__file__).resolve().parents[2]
    cache = root / "data/cache/knowledge/split_docs.json"
    dataset = root / "data/evaluation/project-20261026-r3/api-rag.json"
    if not cache.exists() or not dataset.exists():
        pytest.skip("optional local corpus and frozen regression dataset unavailable")
    documents = [Document(**item) for item in json.loads(cache.read_text(encoding="utf-8"))]
    retriever = HybridRetriever(bm25_top_k=6, vector_top_k=6 if with_vector_distractors else 0)
    retriever.build(documents)
    vector = Mock()
    # Fixed actual corpus fragments, not responses from a remote embedding model.
    vector.similarity_search_with_score.return_value = [(doc, .99) for doc in documents[:6]]
    pipeline = RAGPipeline(Mock(), retriever, vector, SimpleReranker())
    pipeline.documents = documents
    cases = [case for case in json.loads(dataset.read_text(encoding="utf-8"))["cases"] if case["split"] == "regression"]
    failures = []
    for case in cases:
        rows = pipeline.retrieve(case["inputs"]["query"], top_k=10)
        sources = list(dict.fromkeys(row.source_path for row in rows))
        if not any(source in case["oracle"]["relevance"] for source in sources[:3]):
            failures.append((case["case_id"], case["inputs"]["query"], sources))
    assert cases and not failures, failures
    assert vector.similarity_search_with_score.call_count == (len(cases) if with_vector_distractors else 0)
