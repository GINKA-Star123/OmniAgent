from __future__ import annotations

import re

from aiagent.evaluation.contracts import digest

# Only explicit gold provenance, not an arbitrary work mentioned inside a fact.
GOLD_SOURCE_PATTERN = r'\A《(?P<title>[^《》\r\n]+)》(?:“[^“”\r\n]+”)?记载[：:]'
SOURCE_LABEL_PATTERN = r'来源[：:]\s*《(?P<title>[^《》\r\n]+)》'
SOURCE_ALIAS_RULE = {
    "version": "gold-document-md-alias-v1",
    "gold_source_pattern": GOLD_SOURCE_PATTERN,
    "source_label_pattern": SOURCE_LABEL_PATTERN,
    "extensions": [".md"],
    "wrappers": [["（", "）"], ["(", ")"]],
    "eligible_truth": "unverifiable",
    "answer_boundaries": "start/end or sentence punctuation; matching parentheses may enclose label",
    "comparison": "exact; no paths, fuzzy matching, or evidence inference",
}
SOURCE_ALIAS_IDENTITY = {"version": SOURCE_ALIAS_RULE["version"], "sha256": digest(SOURCE_ALIAS_RULE)}


def _document_title(value: str) -> str | None:
    if value != value.strip() or any(char in value for char in ("/", "\\", "\n", "\r")):
        return None
    title = value.removesuffix(".md")
    if not title or title in {".", ".."}:
        return None
    return title


def gold_document_titles(gold: dict[str, str], fact_ids: list[str]) -> list[str]:
    titles = set()
    for fact_id in fact_ids:
        match = re.match(GOLD_SOURCE_PATTERN, gold[fact_id])
        if match and (title := _document_title(match["title"])) is not None:
            titles.add(title)
    return sorted(titles)


def is_evidence_citation_only(quote: str, evidence: dict[str, str]) -> bool:
    """Recognize only structural references to evidence actually supplied to this run."""
    if not re.fullmatch(r'(?:\s*\[[^\[\]\r\n]+\][\s，,。.;；]*)+', quote):
        return False
    identifiers = re.findall(r'\[([^\[\]\r\n]+)\]', quote)
    return bool(identifiers) and all(identifier in evidence for identifier in identifiers)


def is_gold_source_label(quote: str, titles: list[str], answer: str) -> bool:
    text = quote.strip()
    literal = text
    for left, right in SOURCE_ALIAS_RULE["wrappers"]:
        if text.startswith(left) and text.endswith(right):
            text = text[len(left):-len(right)].strip()
            break
    match = re.fullmatch(SOURCE_LABEL_PATTERN, text)
    if not match or _document_title(match["title"]) not in titles:
        return False
    # A partial quote inside a negation or a longer version/year claim is not standalone.
    for occurrence in re.finditer(re.escape(literal), answer):
        start, end = occurrence.span()
        for left, right in SOURCE_ALIAS_RULE["wrappers"]:
            if start and end < len(answer) and answer[start - 1] == left and answer[end] == right:
                start, end = start - 1, end + 1
                break
        prefix, suffix = answer[:start].rstrip(), answer[end:].lstrip()
        if ((not prefix or prefix[-1] in "。！？!?；;.\n")
                and (not suffix or suffix[0] in "。！？!?；;.\n")):
            return True
    return False
