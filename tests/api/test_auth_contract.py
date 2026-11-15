# tests/api/test_auth_contract.py
from __future__ import annotations

import pytest


@pytest.fixture()
def auth_env(monkeypatch, tmp_path):
    from apps.api import auth_store

    monkeypatch.setattr(auth_store.settings, "auth_store_path", str(tmp_path / "auth_store.json"))
    monkeypatch.setattr(auth_store.settings, "auth_registration_enabled", True)
    monkeypatch.setattr(auth_store.settings, "auth_guest_enabled", True)
    monkeypatch.setattr(auth_store.settings, "auth_invite_code", "")
    monkeypatch.setattr(auth_store.settings, "auth_token_ttl_hours", 1)
    monkeypatch.setattr(auth_store.settings, "auth_guest_token_ttl_hours", 1)
    auth_store.reset_auth_store()
    try:
        yield
    finally:
        auth_store.reset_auth_store()


def _register(api_client, username: str = "tester01", password: str = "secret123"):
    return api_client.post(
        "/auth/register",
        json={"username": username, "password": password},
    )


def test_register_and_login(api_client, auth_env):
    response = _register(api_client)
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["user_id"].startswith("user-")
    assert data["token"]
    assert data["expires_at"] > 0

    login = api_client.post(
        "/auth/login",
        json={"username": "tester01", "password": "secret123"},
    ).json()
    assert login["ok"] is True
    assert login["token"] != data["token"]
    assert login["user_id"] == data["user_id"]

    wrong = api_client.post(
        "/auth/login",
        json={"username": "tester01", "password": "wrong-pass"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["ok"] is False

    duplicate = _register(api_client)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "username_taken"

    short_password = _register(api_client, username="tester02", password="123")
    assert short_password.status_code == 400
    assert short_password.json()["code"] == "invalid_password"


def test_guest_identity(api_client, auth_env):
    response = api_client.post("/auth/guest", json={"device_id": "device-demo"})
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["is_guest"] is True
    assert data["user_id"].startswith("guest-")
    assert data["token"]

    # 游客账号不能走密码登录
    login = api_client.post(
        "/auth/login",
        json={"username": data["username"], "password": "anything"},
    )
    assert login.status_code == 401


def test_registration_requires_invite(api_client, auth_env, monkeypatch):
    from apps.api import auth_store

    monkeypatch.setattr(auth_store.settings, "auth_invite_code", "invite-123")

    denied = _register(api_client, username="invite01")
    assert denied.status_code == 403
    assert denied.json()["code"] == "invalid_invite"

    allowed = api_client.post(
        "/auth/register",
        json={"username": "invite01", "password": "secret123", "invite_code": "invite-123"},
    )
    assert allowed.status_code == 200


def test_auth_endpoints_can_be_disabled(api_client, auth_env, monkeypatch):
    from apps.api import auth_store

    monkeypatch.setattr(auth_store.settings, "auth_registration_enabled", False)
    monkeypatch.setattr(auth_store.settings, "auth_guest_enabled", False)

    assert _register(api_client, username="disabled01").status_code == 403
    assert api_client.post("/auth/guest", json={}).status_code == 403


def test_bearer_me_and_principal_match(api_client, auth_env, auth_headers):
    # auth_headers 会把鉴权切到 bearer，并提供静态映射；动态 token 仍走 store 合并。
    registered = _register(api_client, username="bearer01").json()
    headers = {"Authorization": "Bearer " + registered["token"]}

    me = api_client.get("/auth/me", headers=headers)
    body = me.json()
    assert me.status_code == 200
    assert body["user_id"] == registered["user_id"]
    assert body["source"] == "bearer"
    assert body["username"] == "bearer01"

    matched = api_client.post(
        "/chat",
        headers=headers,
        json={"user_id": registered["user_id"], "username": "bearer01", "text": "你好"},
    )
    assert matched.status_code == 200
    assert matched.json()["ok"] is True

    mismatched = api_client.post(
        "/chat",
        headers=headers,
        json={"user_id": "someone-else", "username": "x", "text": "你好"},
    )
    assert mismatched.status_code == 403
    assert mismatched.json()["code"] == "principal_mismatch"


def test_audio_query_token_is_accepted(api_client, auth_env, auth_headers):
    registered = _register(api_client, username="audio01").json()
    token = registered["token"]

    with_header = api_client.get(
        "/audio/not-exists.wav", headers={"Authorization": "Bearer " + token}
    )
    with_query = api_client.get("/audio/not-exists.wav", params={"access_token": token})

    # 资源不存在应为 404；关键是不因鉴权被拒。
    assert with_header.status_code != 401
    assert with_query.status_code != 401
