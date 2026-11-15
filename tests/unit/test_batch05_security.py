from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from aiagent.memory.approved_write import (
    ApprovalError,
    approve_plan,
    approved_metadata,
    verify_approved,
)
from aiagent.memory.memory_safety import MemorySafetyFilter
from aiagent.schemas.memory import MemoryCategory, MemoryStorePlan
from apps.api import user_auth

TOKEN_A = "A" * 43  # 仅测试合成值，不得用作实际部署 Token。
TOKEN_B = "B" * 43


def plan(text="用户喜欢茶。"):
    return MemoryStorePlan(
        should_store=True, status="ready", category=MemoryCategory.PREFERENCE,
        memory_text=text, guard=MemorySafetyFilter().evaluate(text),
    )


def request(headers=(), *, path="/probe", query_string=b""):
    return Request({"type": "http", "method": "GET", "path": path,
                    "headers": list(headers), "query_string": query_string, "server": ("test", 80)})


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setattr(user_auth.settings, "api_auth_mode", "bearer")
    monkeypatch.setattr(user_auth.settings, "api_auth_token_sha256_map", json.dumps({
        hashlib.sha256(TOKEN_A.encode()).hexdigest(): "u1",
        hashlib.sha256(TOKEN_B.encode()).hexdigest(): "u2",
    }))
    monkeypatch.setattr(user_auth.settings, "enable_local_audio_playback", False)
    monkeypatch.setattr(user_auth.settings, "app_env", "test")
    monkeypatch.setattr(user_auth.cloud_settings, "cloud_mode", False)
    return user_auth


def test_payload_is_immutable_and_metadata_has_no_arbitrary_fields():
    payload = approve_plan(plan(), user_id="u1", agent_id="yzl",
                           session_id="password=never-copy-session", turn_id="raw-turn")
    verify_approved(payload)
    with pytest.raises(FrozenInstanceError):
        payload.text = "changed"
    metadata = approved_metadata(payload)
    assert metadata["category"] == "preference"
    assert "password=" not in json.dumps(metadata)
    assert not {"user_name", "policy_reason", "memory_hint", "raw_policy_response"} & metadata.keys()


@pytest.mark.parametrize("field,value", [
    ("text", "用户喜欢咖啡。"), ("user_id", "u2"), ("agent_id", "another-agent"),
    ("source", "user_merge"), ("turn_ref", "changed"),
])
def test_signed_payload_tampering_is_rejected(field, value):
    payload = approve_plan(plan(), user_id="u1", agent_id="yzl")
    with pytest.raises(ApprovalError):
        verify_approved(replace(payload, **{field: value}))


@pytest.mark.parametrize("mutation", [
    {"should_store": False}, {"status": "blocked"}, {"memory_text": "different"},
    {"source": "untrusted_source"},
])
def test_invalid_plan_cannot_be_approved(mutation):
    candidate = plan().model_copy(update=mutation)
    with pytest.raises(ApprovalError):
        approve_plan(candidate, user_id="u1", agent_id="yzl")


def test_sensitive_candidate_never_gets_approval():
    with pytest.raises(ApprovalError):
        approve_plan(plan("password=CANARY_PASSWORD_123456"), user_id="u1", agent_id="yzl")


def test_bearer_principal_ignores_forged_user_header(auth):
    principal = auth.authenticate(request([
        (b"authorization", f"Bearer {TOKEN_A}".encode()), (b"x-user-id", b"u2"),
    ]))
    assert principal.user_id == "u1"


@pytest.mark.parametrize("headers,expected_code", [
    ([], "authentication_required"),
    ([(b"x-user-id", b"u1")], "authentication_required"),
    ([(b"authorization", b"")], "invalid_credentials"),
    ([(b"authorization", b"Bearer short")], "invalid_credentials"),
    ([(b"authorization", f"Bearer {'Z' * 43}".encode())], "invalid_credentials"),
    ([(b"authorization", f"Bearer {TOKEN_A}".encode()),
      (b"authorization", f"Bearer {TOKEN_B}".encode())], "invalid_credentials"),
])
def test_missing_wrong_or_duplicate_credentials_fail(auth, headers, expected_code):
    with pytest.raises(HTTPException) as error:
        auth.authenticate(request(headers))
    assert error.value.status_code == 401
    assert error.value.detail == {"code": expected_code}
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


def test_audio_query_token_authenticates_without_header(auth):
    principal = auth.authenticate(request(
        path="/audio/fixture.wav", query_string=f"access_token={TOKEN_A}".encode(),
    ))
    assert principal.user_id == "u1"
    assert principal.source == "bearer"


@pytest.mark.parametrize("path,headers,query,expected_code", [
    pytest.param("/audio/fixture.wav", [], b"", "authentication_required", id="audio-missing"),
    pytest.param("/audio/fixture.wav", [], b"access_token=short", "invalid_credentials", id="audio-short"),
    pytest.param("/audio/fixture.wav", [], f"access_token={'Z' * 43}".encode(),
                 "invalid_credentials", id="audio-unknown"),
    pytest.param("/chat", [], f"access_token={TOKEN_A}".encode(),
                 "authentication_required", id="chat-query-forbidden"),
    pytest.param("/audio/fixture.wav", [(b"authorization", b"Bearer short")],
                 f"access_token={TOKEN_A}".encode(), "invalid_credentials", id="bad-header-no-query-fallback"),
    pytest.param("/audio/fixture.wav", [
        (b"authorization", f"Bearer {TOKEN_A}".encode()),
        (b"authorization", f"Bearer {TOKEN_B}".encode()),
    ], f"access_token={TOKEN_A}".encode(), "invalid_credentials", id="duplicate-header-no-query-fallback"),
])
def test_audio_query_fallback_preserves_authentication_boundaries(auth, path, headers, query, expected_code):
    with pytest.raises(HTTPException) as error:
        auth.authenticate(request(headers, path=path, query_string=query))
    assert error.value.status_code == 401
    assert error.value.detail == {"code": expected_code}
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


def test_local_dev_is_fixed_and_forbidden_in_production(auth, monkeypatch):
    monkeypatch.setattr(auth.settings, "api_auth_mode", "local-dev")
    monkeypatch.setattr(auth.settings, "api_local_principal", "local-user")
    assert auth.authenticate(request()).user_id == "local-user"
    monkeypatch.setattr(auth.settings, "app_env", "production")
    with pytest.raises(RuntimeError, match="local_dev_auth_forbidden"):
        auth.validate_auth_config()


def test_invalid_mapping_fails_closed_without_echo(auth, monkeypatch):
    monkeypatch.setattr(auth.settings, "api_auth_token_sha256_map", "sensitive-invalid-value")
    with pytest.raises(HTTPException) as error:
        auth.authenticate(request([(b"authorization", f"Bearer {TOKEN_A}".encode())]))
    assert error.value.status_code == 503
    assert "sensitive-invalid-value" not in str(error.value.detail)
