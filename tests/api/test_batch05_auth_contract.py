from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from aiagent.perception.voice_call_store import VoiceRealtimeCallStore
from aiagent.schemas.outputs import OutputEvent, ResponsePacket
from aiagent.services.generation_errors import GenerationUnavailableError
from aiagent.state.private_resources import PrivateResourceStore
from apps.api import user_auth
from apps.api.exception_handlers import http_exception_handler, validation_exception_handler
from apps.api.routes import audio, chat, control, memory, private_files, voice_realtime

TOKEN_A, TOKEN_B = "A" * 43, "B" * 43


def headers(user="u1"):
    return {"Authorization": f"Bearer {TOKEN_A if user == 'u1' else TOKEN_B}"}


@pytest.fixture
def secured(monkeypatch, tmp_path):
    monkeypatch.setattr(user_auth.settings, "api_auth_mode", "bearer")
    monkeypatch.setattr(user_auth.settings, "api_auth_token_sha256_map", json.dumps({
        hashlib.sha256(TOKEN_A.encode()).hexdigest(): "u1",
        hashlib.sha256(TOKEN_B.encode()).hexdigest(): "u2",
    }))
    monkeypatch.setattr(user_auth.settings, "enable_local_audio_playback", False)
    monkeypatch.setattr(user_auth.settings, "app_env", "test")
    monkeypatch.setattr(user_auth.cloud_settings, "cloud_mode", False)
    monkeypatch.setenv("CLOUD_ADMIN_TOKEN", "synthetic-admin-for-tests-only")
    call_store = VoiceRealtimeCallStore(prefix="batch05-http", provider="memory")
    monkeypatch.setattr(voice_realtime, "_CALL_STORE", call_store)
    runtime = Mock()
    runtime.handle_chat_full.return_value = OutputEvent(packet=ResponsePacket(reply_text="正常回答", should_speak=False))
    runtime.get_user_memory_preference.return_value = {"user_id": "u1", "long_term_enabled": True}
    runtime.get_memory_snapshot.return_value = {"user_id": "u1", "total": 0, "layers": []}
    monkeypatch.setattr(chat, "get_runtime", lambda: runtime)
    monkeypatch.setattr(memory, "get_runtime", lambda: runtime)
    monkeypatch.setattr(control, "get_runtime", lambda: runtime)
    root = tmp_path / "private-audio"
    root.mkdir()
    resources = PrivateResourceStore()
    monkeypatch.setattr(audio, "PRIVATE_AUDIO_ROOT", root)
    monkeypatch.setattr(audio, "get_private_resources", lambda: resources)
    app = FastAPI(dependencies=[Depends(user_auth.enforce_http_policy)],
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    for router in (chat.router, memory.router, voice_realtime.router, audio.router,
                   control.router, private_files.router):
        app.include_router(router)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, runtime=runtime, store=call_store,
                              resources=resources, root=root)


def test_chat_identity_contrast_has_zero_unauthorized_side_effect(secured):
    client, runtime = secured.client, secured.runtime
    body = {"user_id": "u1", "text": "你好", "session_id": "logical-one"}
    assert client.post("/chat", json=body).status_code == 401
    assert client.post("/chat", json={**body, "user_id": "u2"}, headers=headers()).status_code == 403
    runtime.handle_chat_full.assert_not_called()
    assert client.post("/chat", json=body, headers=headers()).status_code == 200
    runtime.handle_chat_full.assert_called_once()
    assert runtime.handle_chat_full.call_args.kwargs["user_id"] == "u1"


def test_unauthenticated_response_preserves_bearer_challenge(secured):
    response = secured.client.post("/chat", json={"user_id": "u1", "text": "测试"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == "authentication_required"


def test_validation_does_not_echo_invalid_input(secured):
    canary = "CANARY_INVALID_PRIVATE_INPUT"
    response = secured.client.post(
        "/chat", headers=headers(), json={"user_id": "u1", "text": {"private": canary}},
    )
    assert response.status_code == 422
    assert canary not in response.text
    assert response.json()["detail"]
    assert all(set(item) == {"type", "loc"} for item in response.json()["detail"])


@pytest.mark.parametrize("method,path", [
    ("GET", "/memory/user/u1/snapshot"), ("GET", "/memory/user/u1/audit"),
    ("DELETE", "/memory/user/u1"), ("PATCH", "/memory/user/u1/memories/m1"),
    ("POST", "/memory/user/u1/merge"),
])
def test_cross_user_memory_never_enters_runtime(secured, method, path):
    body = {"memory": "偏好", "merged_memory": "偏好", "memory_ids": ["m1", "m2"]}
    response = secured.client.request(method, path, json=body, headers=headers("u2"))
    assert response.status_code == 403
    assert not secured.runtime.mock_calls


def test_same_user_memory_read_is_allowed(secured):
    response = secured.client.get("/memory/user/u1/snapshot", headers=headers())
    assert response.status_code == 200
    assert response.json()["snapshot"]["user_id"] == "u1"


def test_call_state_end_interrupt_and_turn_are_owner_scoped(secured):
    client = secured.client
    started = client.post("/voice/realtime/start", json={"user_id": "u1"}, headers=headers())
    assert started.status_code == 200
    call_id = started.json()["call_id"]
    before = client.get(f"/voice/realtime/state/{call_id}", headers=headers()).json()["call"]
    assert client.get(f"/voice/realtime/state/{call_id}", headers=headers("u2")).status_code == 404
    for path in ("end", "interrupt"):
        assert client.post(f"/voice/realtime/{path}", json={"call_id": call_id},
                           headers=headers("u2")).status_code == 404
    response = client.post("/voice/realtime/turn", data={"user_id": "u2", "call_id": call_id},
                           files={"file": ("test.wav", b"not-decoded", "audio/wav")}, headers=headers("u2"))
    assert response.status_code == 404
    after = client.get(f"/voice/realtime/state/{call_id}", headers=headers()).json()["call"]
    assert after["turn_count"] == before["turn_count"] == 0
    assert after["interrupt_count"] == before["interrupt_count"] == 0
    assert client.post("/voice/realtime/end", json={"call_id": call_id}, headers=headers()).status_code == 200


@pytest.mark.parametrize("operation", ["state", "turn", "interrupt", "end"])
def test_call_not_found_stage_is_preserved_without_disclosing_ownership(secured, operation):
    client = secured.client
    started = client.post("/voice/realtime/start", json={"user_id": "u1"}, headers=headers())
    assert started.status_code == 200
    owned_call_id = started.json()["call_id"]
    payloads = []

    for call_id in ("missing-call-id", owned_call_id):
        if operation == "state":
            response = client.get(f"/voice/realtime/state/{call_id}", headers=headers("u2"))
        elif operation == "turn":
            response = client.post(
                "/voice/realtime/turn", headers=headers("u2"),
                data={"call_id": call_id, "user_id": "u2"},
                files={"file": ("test.wav", b"not-decoded", "audio/wav")},
            )
        else:
            response = client.post(
                f"/voice/realtime/{operation}", headers=headers("u2"), json={"call_id": call_id},
            )

        assert response.status_code == 404
        payload = response.json()
        assert payload["ok"] is False
        assert payload["stage"] == f"voice_realtime_{operation}"
        assert payload["code"] == "call_not_found"
        assert not {"call", "call_id", "user_id"} & payload.keys()
        payloads.append({key: value for key, value in payload.items() if key != "request_id"})

    assert payloads[0] == payloads[1]
    state = client.get(f"/voice/realtime/state/{owned_call_id}", headers=headers())
    assert state.status_code == 200
    call = state.json()["call"]
    assert call["status"] == "active"
    assert call["phase"] == "idle"
    assert call["turn_count"] == 0
    assert call["interrupt_count"] == 0
    assert not secured.runtime.mock_calls


def test_audio_download_contrast_and_unknown_owner(secured):
    target = secured.root / "owned.wav"
    target.write_bytes(b"synthetic-audio")
    secured.resources.register("audio", target.name, "u1", str(target))
    assert secured.client.get("/audio/owned.wav").status_code == 401
    assert secured.client.get("/audio/owned.wav", headers=headers("u2")).status_code == 404
    good = secured.client.get("/audio/owned.wav", headers=headers())
    assert good.status_code == 200 and good.content == b"synthetic-audio"
    assert good.headers["cache-control"] == "private, no-store"
    (secured.root / "legacy.wav").write_bytes(b"legacy")
    assert secured.client.get("/audio/legacy.wav", headers=headers()).status_code == 404


def test_registered_path_outside_root_is_still_rejected(secured, tmp_path):
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"private")
    secured.resources.register("audio", "outside.wav", "u1", str(outside))
    assert secured.client.get("/audio/outside.wav", headers=headers()).status_code == 404


def test_global_control_requires_admin_not_just_user(secured):
    response = secured.client.post("/control/pause", json={"paused": True}, headers=headers())
    assert response.status_code == 403
    secured.runtime.pause_dialogue.assert_not_called()


def test_static_download_is_not_public(secured, monkeypatch, tmp_path):
    monkeypatch.setattr(private_files.cloud_settings, "storage_provider", "local")
    monkeypatch.setattr(private_files.cloud_settings, "local_storage_root", str(tmp_path))
    (tmp_path / "object.bin").write_bytes(b"private-object")
    assert secured.client.get("/cloud-files/object.bin").status_code == 403
    assert secured.client.get("/cloud-files/object.bin", headers=headers()).status_code == 403
    result = secured.client.get("/cloud-files/object.bin",
                               headers={"X-Cloud-Admin-Token": "synthetic-admin-for-tests-only"})
    assert result.status_code == 200 and result.content == b"private-object"


def test_generation_failure_contract_not_echo_and_not_audio(secured, caplog):
    secured.runtime.handle_chat_full.side_effect = GenerationUnavailableError()
    response = secured.client.post("/chat", json={"user_id": "u1", "text": "RAW_CANARY_INPUT"}, headers=headers())
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "generation_unavailable"
    assert body["should_speak"] is False and body["should_store_memory"] is False
    assert body["audio_segments"] == []
    assert "RAW_CANARY_INPUT" not in response.text
    assert "RAW_CANARY_INPUT" not in caplog.text


def test_main_app_does_not_mount_public_static_files(secured):
    from starlette.routing import Mount

    from apps.api.http_server import app

    assert not any(isinstance(route, Mount) and route.path == "/cloud-files" for route in app.routes)
    assert app.docs_url is None and app.openapi_url is None
