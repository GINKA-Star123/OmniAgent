from __future__ import annotations

import hashlib
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from aiagent.graphs.metadata_utils import metadata_strings
from aiagent.schemas.outputs import OutputEvent, ResponsePacket
from aiagent.services.vision_service import VisionService
from aiagent.vision.image_store import ImageStore
from apps.api import user_auth
from apps.api.routes import multimodal_chat, vision

TOKEN = "G" * 43
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PATHS = ("/vision/analyze", "/vision/chat", "/chat/multimodal")


def gif_bytes():
    frames = [Image.new("RGB", (24, 24), color) for color in ("red", "blue", "green")]
    with BytesIO() as buffer:
        frames[0].save(
            buffer, format="GIF", save_all=True, append_images=frames[1:],
            duration=100, loop=0, disposal=2,
        )
        result = buffer.getvalue()
    for frame in frames:
        frame.close()
    return result


class EmptyRetriever:
    def retrieve(self, image_path, top_k=5):
        return []


class RuntimeAdapter:
    def __init__(self, service):
        self.service = service
        self.calls = 0

    def analyze_image_upload(self, file_obj, filename, user_prompt="", user_id="guest"):
        self.calls += 1
        return self.service.analyze_upload(file_obj, filename, user_prompt, user_id)

    def handle_vision_chat_upload(self, file_obj, filename, **kwargs):
        result = self.analyze_image_upload(
            file_obj, filename, kwargs.get("user_prompt", ""), kwargs["user_id"],
        )
        return {
            "chat_output": OutputEvent(packet=ResponsePacket(reply_text="synthetic", should_speak=False)),
            "vision_state": {"vision_result": result},
        }

    def handle_multimodal_chat_upload(self, file_obj, filename, **kwargs):
        result = None
        if file_obj is not None:
            result = self.analyze_image_upload(file_obj, filename, kwargs.get("text", ""), kwargs["user_id"])
        return OutputEvent(packet=ResponsePacket(
            reply_text="synthetic", should_speak=False,
            metadata={} if result is None else metadata_strings(result.metadata),
        ))


@pytest.fixture(params=[False, True], ids=["local", "cloud"])
def secured_gif(request, monkeypatch, tmp_path):
    monkeypatch.setattr(user_auth.settings, "api_auth_mode", "bearer")
    monkeypatch.setattr(user_auth.settings, "api_auth_token_sha256_map", json.dumps({
        hashlib.sha256(TOKEN.encode()).hexdigest(): "u1",
    }))
    monkeypatch.setattr(user_auth.settings, "enable_local_audio_playback", False)
    monkeypatch.setattr(user_auth.settings, "app_env", "test")
    monkeypatch.setattr(user_auth.cloud_settings, "cloud_mode", request.param)
    monkeypatch.setattr(user_auth.cloud_settings, "execution_state_mode", "redis" if request.param else "local")
    monkeypatch.setattr(user_auth.cloud_settings, "voice_call_store_provider", "redis")
    monkeypatch.setattr(user_auth.cloud_settings, "voice_call_store_fail_open", False)
    monkeypatch.setattr(vision.cloud_settings, "cloud_mode", request.param)
    monkeypatch.setattr(multimodal_chat.cloud_settings, "cloud_mode", request.param)
    service = VisionService(
        image_store=ImageStore(upload_dir=tmp_path / "uploads"),
        character_retriever=EmptyRetriever(), provider="mock",
    )
    runtime = RuntimeAdapter(service)
    monkeypatch.setattr(vision, "get_runtime", lambda: runtime)
    monkeypatch.setattr(multimodal_chat, "get_runtime", lambda: runtime)
    app = FastAPI(dependencies=[Depends(user_auth.enforce_http_policy)])
    app.include_router(vision.router)
    app.include_router(multimodal_chat.router)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, runtime=runtime)


@pytest.mark.parametrize("path", PATHS)
def test_three_routes_accept_real_gif_bytes(secured_gif, path):
    response = secured_gif.client.post(
        path, headers=AUTH,
        data={"user_id": "u1", "prompt": "描述可见变化", "text": "描述可见变化"},
        files={"file": ("sample.gif", gif_bytes(), "image/gif")},
    )
    assert response.status_code == 200
    payload = response.json()
    if path == "/vision/analyze":
        metadata = payload["result"]["metadata"]
    elif path == "/vision/chat":
        metadata = payload["vision"]["result"]["metadata"]
    else:
        metadata = payload["metadata"]
    assert str(metadata["vision_gif_frame_count"]) == "3"
    assert metadata["vision_animation_inference"] == "mock"
    assert str(metadata["vision_gif_sent_frame_count"]) == "0"
    assert secured_gif.runtime.calls == 1


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("bad", [
    pytest.param(b"not-a-gif" * 20, id="invalid-signature"),
    pytest.param("truncated", id="missing-trailer"),
    pytest.param("middle", id="truncated-frame"),
])
def test_decode_failures_are_400_not_500_or_cloud_fallback(secured_gif, path, bad):
    if bad == "truncated":
        content = gif_bytes()[:-1]
    elif bad == "middle":
        valid = gif_bytes()
        content = valid[:len(valid) // 2] + b";"
    else:
        content = bad
    response = secured_gif.client.post(
        path, headers=AUTH, data={"user_id": "u1"},
        files={"file": ("broken.gif", content, "image/gif")},
    )
    assert response.status_code == 400
    assert "invalid_or_unsupported_image" in response.text
    assert secured_gif.runtime.calls == 1
    assert list(secured_gif.runtime.service.image_store.upload_dir.iterdir()) == []


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("content_type", ["application/pdf", "image/bmp"])
def test_mime_precheck_rejects_before_runtime(secured_gif, path, content_type):
    response = secured_gif.client.post(
        path, headers=AUTH, data={"user_id": "u1"},
        files={"file": ("sample.gif", gif_bytes(), content_type)},
    )
    assert response.status_code == 400
    assert secured_gif.runtime.calls == 0


@pytest.mark.parametrize("path", PATHS)
def test_auth_and_owner_contrast_runs_before_gif_decoding(secured_gif, path):
    for headers, user_id, expected in (({}, "u1", 401), (AUTH, "u2", 403)):
        response = secured_gif.client.post(
            path, headers=headers, data={"user_id": user_id},
            files={"file": ("broken.gif", b"bad" * 100, "image/gif")},
        )
        assert response.status_code == expected
    assert secured_gif.runtime.calls == 0
    assert list(secured_gif.runtime.service.image_store.upload_dir.iterdir()) == []


def test_schema_declares_real_limits_and_new_memory_reason(secured_gif):
    response = secured_gif.client.get("/vision/schema", headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert "image/gif" in payload["allowed_content_types"]
    assert "gif_transient_media" in payload["memory_reason_codes"]
    assert payload["gif"]["requires_multi_image_provider"] is True
    assert payload["gif"]["limits"]["max_samples"] == 6
    assert payload["gif"]["limits"]["max_frames"] == 120


@pytest.mark.parametrize("path", PATHS)
def test_model_json_value_error_is_not_mislabeled_as_upload_400(secured_gif, path, monkeypatch):
    def broken_model(**kwargs):
        raise ValueError("synthetic_invalid_model_json")

    monkeypatch.setattr(secured_gif.runtime.service, "_analyze_with_model", broken_model)
    response = secured_gif.client.post(
        path, headers=AUTH, data={"user_id": "u1"},
        files={"file": ("valid.gif", gif_bytes(), "image/gif")},
    )
    assert response.status_code in {500, 503}
    assert secured_gif.runtime.calls == 1


def test_multimodal_text_without_file_is_still_valid(secured_gif):
    response = secured_gif.client.post(
        "/chat/multimodal", headers=AUTH, data={"user_id": "u1", "text": "你好"},
    )
    assert response.status_code == 200
    assert secured_gif.runtime.calls == 0


@pytest.mark.parametrize("path", PATHS)
def test_actual_offline_runtime_gif_regression(path, offline_runtime_assets, monkeypatch):
    # Uses the existing offline fixtures and the real app/runtime, not RuntimeAdapter.
    monkeypatch.setattr(user_auth.settings, "api_auth_mode", "bearer")
    monkeypatch.setattr(user_auth.settings, "api_auth_token_sha256_map", json.dumps({
        hashlib.sha256(TOKEN.encode()).hexdigest(): "u1",
    }))
    monkeypatch.setattr(user_auth.settings, "enable_local_audio_playback", False)
    monkeypatch.setattr(user_auth.settings, "app_env", "test")
    monkeypatch.setattr(user_auth.cloud_settings, "cloud_mode", False)
    monkeypatch.setattr(user_auth.cloud_settings, "execution_state_mode", "local")
    from apps.api.http_server import app
    from apps.core.runtime_registry import reset_runtime

    reset_runtime()
    try:
        with TestClient(app) as client:
            response = client.post(
                path, headers=AUTH,
                data={"user_id": "u1", "prompt": "看图", "text": "看图"},
                files={"file": ("sample.gif", gif_bytes(), "image/gif")},
            )
        assert response.status_code == 200
        payload = response.json()
        if path == "/vision/analyze":
            metadata = payload["result"]["metadata"]
        elif path == "/vision/chat":
            metadata = payload["vision"]["result"]["metadata"]
        else:
            metadata = payload["metadata"]
        assert str(metadata["vision_gif_frame_count"]) == "3"
        assert metadata["vision_animation_inference"] == "mock"
        assert str(metadata["vision_gif_sent_frame_count"]) == "0"
    finally:
        reset_runtime()
