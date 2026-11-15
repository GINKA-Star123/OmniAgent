from __future__ import annotations

from tests.helpers.api_contract import (
    assert_json_response,
    assert_ok_response,
)


def test_session_open_contract(api_client, test_user):
    response = api_client.post(
        "/session/open",
        json={
            "user_id": test_user["user_id"],
            "username": test_user["username"],
            "entry": "chat_page",
            "recent_topic": "",
        },
    )
    data = assert_json_response(response)

    assert_ok_response(data)
    assert data.get("degraded",False) is False

    assert "opening" in data
    assert "presence" in data
    assert "live2d" in data
    assert "memory" in data

    opening = data["opening"]
    presence = data["presence"]
    live2d = data["live2d"]
    memory = data["memory"]

    assert isinstance(opening, dict)
    assert isinstance(presence, dict)
    assert isinstance(live2d, dict)
    assert isinstance(memory, dict)

    assert "kind" in opening
    assert "text" in opening
    assert "should_speak" in opening

    assert "state" in presence
    assert "mood" in presence
    assert "energy" in presence
    assert "fatigue" in presence
    assert "curiosity" in presence

    assert "expression" in live2d
    assert "motion" in live2d


def test_session_open_failure_keeps_contract_and_natural_fallback(api_client, test_user, monkeypatch):
    from unittest.mock import AsyncMock

    from apps.api.routes import session

    monkeypatch.setattr(
        session.presence_service, "open_session",
        AsyncMock(side_effect=RuntimeError("synthetic-store-error")),
    )
    response = api_client.post("/session/open", json={
        "user_id": test_user["user_id"], "username": test_user["username"],
    })
    data = assert_json_response(response)
    assert_ok_response(data)
    assert data["degraded"] is True
    assert data["opening"]["text"] == "来啦，想说什么就说。"
    assert data["opening"]["should_speak"] is True
    assert "synthetic-store-error" not in response.text
    for field in ("presence", "live2d", "memory", "metadata"):
        assert isinstance(data[field], dict)
