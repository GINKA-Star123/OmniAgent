from __future__ import annotations

import re

from aiagent.knowledge.profile_fields import content_profile_fields, matched_profile_sources, query_profile_fields
from aiagent.knowledge.query_normalizer import matches_profile_subject
from aiagent.knowledge.retriever import RetrievedChunk


class SimpleReranker:
    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int = 4,
    ) -> list[RetrievedChunk]:
        query_lower = query.lower()
        fields = query_profile_fields(query)
        profile_sources = matched_profile_sources(query, (chunk.source_path for chunk in chunks)) if fields else set()
        reranked: list[RetrievedChunk] = []

        for chunk in chunks:
            score = chunk.score
            if chunk.source_path in profile_sources:
                # Named source and the requested explicit field outrank generic profile-word overlap.
                score += 0.20
                matched_fields = fields.intersection(content_profile_fields(chunk.content))
                score += 0.25 * len(matched_fields) / len(fields)
            if self._has_explicit_alias_match(query_lower, chunk.content):
                score += 0.08

            if "bm25" in chunk.retrieval_sources and "vector" in chunk.retrieval_sources:
                score += 0.08

            if chunk.cosine_score is not None:
                score += chunk.cosine_score * 0.04

            if chunk.bm25_rank is not None:
                score += max(0.0, 0.04 - chunk.bm25_rank * 0.003)

            if chunk.vector_rank is not None:
                score += max(0.0, 0.04 - chunk.vector_rank * 0.003)

            if chunk.title and chunk.title.lower() in query_lower:
                score += 0.03

            if self._has_exact_term_overlap(query_lower, chunk):
                score += 0.03

            content_len = len(chunk.content)
            if 120 <= content_len <= 1200:
                score += 0.02

            reranked.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    source_path=chunk.source_path,
                    content=chunk.content,
                    score=score,
                    bm25_rank=chunk.bm25_rank,
                    vector_rank=chunk.vector_rank,
                    cosine_score=chunk.cosine_score,
                    retrieval_sources=chunk.retrieval_sources,
                )
            )

        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked[:top_k]

    @staticmethod
    def _has_profile_subject_match(query_lower: str, chunk: RetrievedChunk) -> bool:
        return matches_profile_subject(query_lower, chunk.source_path)

    @staticmethod
    def _has_explicit_alias_match(query_lower: str, content: str) -> bool:
        # Only declared aliases count, not incidental names in narrative text.
        declarations = re.findall(
            r"^\s*(?:[-*]\s+)?(?:\*\*)?(?:别称|别名|又称|英文名|aliases?)"
            r"(?:\*\*)?\s*[:：]\s*([^\n]+)",
            content, flags=re.MULTILINE | re.IGNORECASE,
        )
        for declaration in declarations:
            declaration = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", declaration)
            declaration = re.sub(r"\[\^[^\]]*\]", "", declaration).replace("*", "")
            for alias in re.split(r"[、,，;；/|（）()。\s]+", declaration.lower()):
                if len(alias) < 2:
                    continue
                pattern = re.escape(alias)
                if alias.isascii():
                    pattern = rf"(?<![a-z0-9_./:-]){pattern}(?![a-z0-9_./:-])"
                if re.search(pattern, query_lower):
                    return True
        return False

    def _has_exact_term_overlap(self, query_lower: str, chunk: RetrievedChunk) -> bool:
        important_terms = [
            "洛天依",
            "天依",
            "乐正绫",
            "阿绫",
            "阿绫红",
            "应援词",
            "应援口号",
            "口号",
            "华风夏韵",
            "洛水天依",
            "歌曲",
            "专辑",
            "生日",
            "代表色",
            "基本资料",
            "相关CP",
            "南北组",
            "洛南绫北",
            "声源",
        ]

        content = f"{chunk.title}\n{chunk.content}".lower()
        return any(term.lower() in query_lower and term.lower() in content for term in important_terms)
