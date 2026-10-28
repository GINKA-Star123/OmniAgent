from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import PurePosixPath

from aiagent.knowledge.query_normalizer import is_birthday_fact_query, normalize_aliases

# Retrieval intent and explicit document fields only; no answer values or evaluation data.
_QUERY_FIELDS = {
    "color": r"代表色|应援色",
    "voice": r"声源|声音提供者|中之人|配音演员",
    "age": r"年龄|几岁",
    "height": r"身高|多高",
    "group": r"所属团体|属于哪个团体|哪个社团|所属社团",
    "hair": r"发色|头发.{0,8}颜色",
    "eyes": r"瞳色|眸色|眼睛.{0,8}颜色",
    "spirit": r"音之精灵",
    "release": r"发布日|发布日期|发行日期|发行时间|配布日",
    "alias": r"别称|别名|又称",
}
_FIELD_GROUPS = {
    "生日": "birthday", "代表色": "color", "应援色": "color",
    "声源": "voice", "多位声源": "voice", "声音提供者": "voice", "中之人": "voice",
    "年龄": "age", "身高": "height", "所属团体": "group", "所属社团": "group",
    "发色": "hair", "多种发色": "hair", "瞳色": "eyes", "多种瞳色": "eyes", "眸色": "eyes",
    "音之精灵": "spirit", "发布日": "release", "发布日期": "release",
    "发行日期": "release", "配布日": "release", "别称": "alias", "别名": "alias",
}
_FIELD = re.compile(
    r"^[ \t]*(?:[-*][ \t]+)?(?:\*\*)?(?P<label>" + "|".join(map(re.escape, _FIELD_GROUPS))
    + r")(?:\*\*)?[ \t]*[:：][ \t]*\S[^\r\n]*", re.MULTILINE,
)
_NON_PROFILE_TASKS = (
    "歌曲", "曲子", "专辑", "生贺", "诞生祭", "活动", "直播", "演唱会",
    "写一", "创作", "设计", "祝福", "贺词", "贺图", "礼物", "派对",
)


def query_profile_fields(query: str) -> frozenset[str]:
    if any(term in query for term in _NON_PROFILE_TASKS):
        return frozenset()
    fields = {key for key, pattern in _QUERY_FIELDS.items() if re.search(pattern, query)}
    if is_birthday_fact_query(query):
        fields.add("birthday")
    return frozenset(fields)


def content_profile_fields(content: str) -> frozenset[str]:
    return frozenset(_FIELD_GROUPS[match["label"]] for match in _FIELD.finditer(content))


def matched_profile_sources(query: str, sources: Iterable[str]) -> set[str]:
    def matches(text: str) -> set[str]:
        hits = []
        for source in sources:
            name = PurePosixPath(source.replace("\\", "/")).stem.lower()
            if not name:
                continue
            pattern = re.escape(name)
            if len(name) == 1:
                field_words = "|".join(("生日", *_QUERY_FIELDS.values()))
                pattern = (rf"(?:\A(?:请问[ \t]*)?|(?<=[《“「])){pattern}"
                           rf"(?=[》”」]|(?:的)?(?:设定)?(?:{field_words}))")
            elif name[0].isascii():
                pattern = rf"(?<![a-z0-9_./:+-]){pattern}"
            for match in re.finditer(pattern + r"(?![a-z0-9_./:+-])", text.lower()):
                hits.append((source, match.start(), match.end()))
        # Prefer a complete compound name to a shorter document name inside it.
        return {source for source, start, end in hits if not any(
            other_start <= start and end <= other_end and other_end - other_start > end - start
            for _, other_start, other_end in hits
        )}

    sources = tuple(dict.fromkeys(sources))
    direct = matches(query)
    return direct or matches(normalize_aliases(query))
