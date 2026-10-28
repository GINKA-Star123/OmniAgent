import pytest

from aiagent.memory.mem0_memory import MemoryHit
from aiagent.memory.memory_deduper import MemoryDeduper


def test_memory_deduper_detects_similar_existing_hit():
    deduper = MemoryDeduper()
    result = deduper.check(
        candidate="用户喜欢川菜",
        hits=[
            MemoryHit(
                id="m1",
                memory="用户很喜欢川菜。",
            )
        ],
    )

    assert result.duplicate is True
    assert result.matched_memory_id == "m1"


def test_memory_deduper_allows_new_fact():
    deduper = MemoryDeduper()
    result = deduper.check(
        candidate="用户喜欢晚上写代码",
        hits=[
            MemoryHit(
                id="m1",
                memory="用户喜欢川菜。",
            )
        ],
    )

    assert result.duplicate is False


@pytest.mark.parametrize(("old", "new"), [
    ("用户喜欢听索韵rila的歌曲。", "用户已经不喜欢听索韵rila的歌曲了。"),
    ("用户已经不喜欢听索韵rila的歌曲了。", "用户喜欢听索韵rila的歌曲。"),
    ("用户想购买这个歌手的数字专辑。", "用户不想购买这个歌手的数字专辑。"),
    ("The user likes listening to this singer.", "The user does not like listening to this singer."),
    ("The user likes listening to this singer.", "The user doesn't like listening to this singer."),
])
@pytest.mark.parametrize("via_context", [False, True])
def test_polarity_update_is_not_a_duplicate(old, new, via_context):
    result = MemoryDeduper().check(
        candidate=new,
        hits=[] if via_context else [MemoryHit(id="old", memory=old)],
        existing_context=f"1. {old}" if via_context else "",
    )
    assert result.duplicate is False


def test_repeated_negative_preference_is_still_deduplicated():
    result = MemoryDeduper().check(
        candidate="用户不喜欢听索韵rila的歌曲。",
        hits=[MemoryHit(id="negative", memory="用户不喜欢听索韵rila的歌曲。")],
    )
    assert result.duplicate is True
    assert result.matched_memory_id == "negative"
