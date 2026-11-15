import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aiagent.presence.models import SessionOpenRequest, SessionOpenResponse, SessionSnapshot
from aiagent.presence.opening_generator import choose_opening_kind, generate_opening_text
from aiagent.presence.service import OPENING_COOLDOWN, PresenceService


def test_opening_cooldown_is_ten_minutes():
    snapshot = SessionSnapshot(
        user_id="u1",
        username="tester",
        last_opening_shown_at=datetime.now(UTC),
    )

    assert snapshot.last_opening_shown_at is not None
    assert OPENING_COOLDOWN.total_seconds() == 600


@pytest.mark.parametrize("kind", [
    "first_meet", "short_return", "same_day_return", "next_day_return",
    "long_absence", "late_night", "task_resume",
])
def test_openings_are_spoken_dialogue_not_system_states(kind):
    snapshot = SessionSnapshot(user_id="fixture", unfinished_hint="修改副歌")
    text = generate_opening_text(
        kind=kind, now=datetime(2026, 11, 14, 20, tzinfo=UTC), snapshot=snapshot,
    )
    assert text
    for phrase in ("待机", "低能量模式", "整理状态", "保持着状态", "一直在等你"):
        assert phrase not in text


def test_return_openings_rotate_but_are_stable_for_same_snapshot():
    now = datetime(2026, 11, 14, 20, tzinfo=UTC)
    snapshot = SessionSnapshot(user_id="fixture")
    first = generate_opening_text(kind="same_day_return", now=now, snapshot=snapshot)
    assert first == generate_opening_text(kind="same_day_return", now=now, snapshot=snapshot)
    variants = {
        generate_opening_text(
            kind="same_day_return", now=now,
            snapshot=snapshot.model_copy(update={"open_count": count}),
        )
        for count in range(3)
    }
    assert len(variants) == 3


def test_topic_resume_uses_only_stored_topic_and_does_not_claim_offline_thinking():
    snapshot = SessionSnapshot(user_id="fixture", last_topic="吉他  节奏")
    text = generate_opening_text(
        kind="same_day_return", now=datetime(2026, 11, 14, 20, tzinfo=UTC),
        snapshot=snapshot,
    )
    assert "吉他 节奏" in text
    assert "刚刚还在想" not in text
    assert "排练" not in text


def test_late_night_contrasts_with_daytime_and_does_not_pressure_return():
    snapshot = SessionSnapshot(user_id="fixture", open_count=2,
                               last_opened_at=datetime(2026, 11, 14, 10, tzinfo=UTC))
    night = datetime(2026, 11, 14, 23, tzinfo=UTC)
    assert choose_opening_kind(night, snapshot) == "late_night"
    snapshot.mood.fatigue = 0.9
    text = generate_opening_text(kind="late_night", now=night, snapshot=snapshot)
    assert "不用硬撑" in text
    assert "小声陪你" not in text


def test_open_session_preserves_cooldown_and_updates_snapshot_without_model_calls():
    now = datetime(2026, 11, 14, 20, tzinfo=UTC)
    snapshot = SessionSnapshot(
        user_id="fixture", open_count=4,
        last_opened_at=now - timedelta(minutes=1),
        last_opening_shown_at=now - timedelta(minutes=1),
    )
    store = SimpleNamespace(
        get_snapshot=AsyncMock(return_value=snapshot), save_snapshot=AsyncMock(),
    )
    result = asyncio.run(PresenceService(store).open_session(
        SessionOpenRequest(user_id="fixture", client_time=now),
    ))
    assert result.opening.text == ""
    assert result.opening.should_speak is False
    assert result.memory["opening_suppressed"] is True
    assert result.memory["open_count"] == 5
    assert store.save_snapshot.await_args.args[0].last_opening_shown_at == snapshot.last_opening_shown_at


def test_open_session_keeps_payload_contract_with_new_dialogue():
    snapshot = SessionSnapshot(user_id="fixture")
    store = SimpleNamespace(
        get_snapshot=AsyncMock(return_value=snapshot), save_snapshot=AsyncMock(),
    )
    result = asyncio.run(PresenceService(store).open_session(
        SessionOpenRequest(
            user_id="fixture", client_time=datetime(2026, 11, 14, 20, tzinfo=UTC),
        ),
    ))
    restored = SessionOpenResponse.model_validate(result.model_dump(mode="json"))
    assert restored.opening.kind == "first_meet"
    assert restored.opening.should_speak is True
    assert "阿绫" in restored.opening.text or "乐正绫" in restored.opening.text
    assert restored.memory["opening_suppressed"] is False
    store.save_snapshot.assert_awaited_once()
