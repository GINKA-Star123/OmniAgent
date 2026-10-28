from __future__ import annotations

import pytest

from aiagent.knowledge.query_normalizer import (
    expand_domain_terms,
    is_birthday_fact_query,
    normalize_aliases,
    normalize_rag_query,
)


def test_normalize_aliases_keeps_legacy_behavior():
    normalized = normalize_aliases("墨姐是谁")

    assert "墨姐" in normalized
    assert "墨清弦" in normalized


def test_normalize_aliases_expands_english_identifier():
    normalized = normalize_aliases("乐正绫是谁")

    assert "YueZhengling" in normalized
    assert "yuezhengling" in normalized
    assert "阿绫" in normalized


def test_normalize_aliases_expands_from_english_query():
    normalized = normalize_aliases("LuoTianyi 的设定")

    assert "洛天依" in normalized
    assert "天依" in normalized


def test_normalize_aliases_keeps_unrelated_query_unchanged():
    query = "今天天气怎么样"

    assert normalize_aliases(query) == query


@pytest.mark.parametrize(("alias", "canonical", "english"), [
    ("绫妹", "乐正绫", "YueZhengling"),
    ("牙哥", "乐正龙牙", "YueZhenglongya"),
    ("阿和", "言和", "YanHe"),
])
def test_short_character_alias_query_expands_and_remains_idempotent(alias, canonical, english):
    normalized = normalize_rag_query(f"{alias}是谁")

    assert canonical in normalized.split()
    assert english in normalized.split()
    assert normalize_rag_query(normalized) == normalized


def test_expand_domain_terms_adds_fan_chant_terms():
    expanded = expand_domain_terms("应援词")

    assert "华风夏韵" in expanded
    assert "洛水天依" in expanded


def test_expand_domain_terms_returns_original_when_no_trigger():
    assert expand_domain_terms("随便聊聊") == "随便聊聊"


def test_normalize_rag_query_handles_blank_input():
    assert normalize_rag_query("") == ""
    assert normalize_rag_query("   ") == ""


def test_normalize_rag_query_is_idempotent():
    once = normalize_rag_query("阿绫的应援词是什么")
    twice = normalize_rag_query(once)

    assert once == twice

def test_normalize_aliases_masks_domain_terms():
    """S1 回归：领域词"洛水天依"内部的"天依"不应被当成角色命中。"""

    normalized = normalize_aliases("洛水天依是谁")

    assert "LuoTianyi" not in normalized
    assert normalized == "洛水天依是谁"


def test_expand_domain_terms_reaches_fixed_point():
    """S2 回归：term/trigger 交叉的规则必须一趟到位。"""

    expanded = expand_domain_terms("设定")

    assert "阿绫红" in expanded          # 来自 代表色 规则（被 设定 的 term 触发）
    assert expand_domain_terms(expanded) == expanded


@pytest.mark.parametrize("query", ["猫尾++生日是几月几日？", "欧阳夜语的诞生日", "星桥生日", "牙哥的生日是什么时候？"])
def test_profile_birthday_does_not_expand_to_events(query):
    normalized = normalize_rag_query(query)
    assert "诞生祭" not in normalized
    assert "生贺曲" not in normalized
    assert is_birthday_fact_query(query)
    assert normalize_rag_query(normalized) == normalized


@pytest.mark.parametrize("query", ["猫尾++有哪些生贺曲？", "星桥的生日活动", "星桥的诞生祭", "星桥生日会", "星桥的生日歌曲"])
def test_explicit_birthday_music_and_events_still_expand(query):
    normalized = normalize_rag_query(query)
    assert "诞生祭" in normalized and "生贺曲" in normalized
    assert not is_birthday_fact_query(query)
    assert normalize_rag_query(normalized) == normalized


@pytest.mark.parametrize("query", [
    "为星桥写一段生日祝福", "设计星桥生日礼物", "猫尾++是谁", "有哪些歌曲？",
    "星桥生日前一天发布了哪首歌", "星桥生日当天有什么节目",
])
def test_other_intents_are_not_treated_as_birthday_dates(query):
    assert not is_birthday_fact_query(query)


def test_profile_expansion_does_not_transitively_add_birthday_music():
    query = normalize_rag_query("角色资料介绍")
    assert "生日" in query
    assert "生贺曲" not in query and "诞生祭" not in query
