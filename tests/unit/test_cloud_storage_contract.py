from __future__ import annotations

from pathlib import Path

import pytest

from cloud.config import cloud_settings
from cloud.object_storage import reset_object_store_for_tests
from tests.helpers.api_contract import (
    assert_error_response,
    assert_json_response,
    assert_ok_response,
)


def test_cloud_ready_contract(api_client, admin_headers):
    response = api_client.get("/cloud/ready", headers=admin_headers)
    data = assert_json_response(response)

    assert_ok_response(data)
    assert "cloud_mode" in data
    assert "region" in data
    assert "redis" in data
    assert "storage" in data
    assert "gpu" in data

    assert "provider" in data["storage"]
    assert "bucket_configured" in data["storage"]


def test_cloud_limits_contract(api_client, admin_headers):
    response = api_client.get("/cloud/limits", headers=admin_headers)
    data = assert_json_response(response)

    assert_ok_response(data)
    assert "rate_limit_enabled" in data
    assert "inflight_limit_enabled" in data
    assert "limits" in data

    limits = data["limits"]

    for field in [
        "global_inflight",
        "chat_inflight",
        "multimodal_inflight",
        "voice_inflight",
        "rebuild_inflight",
        "chat_per_minute",
        "multimodal_per_minute",
        "voice_per_minute",
        "rebuild_per_minute",
    ]:
        assert field in limits


def test_direct_upload_contract(api_client, admin_headers, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        cloud_settings,
        "local_storage_root",
        str(tmp_path),
    )
    monkeypatch.setattr(
        cloud_settings,
        "storage_provider",
        "local",
    )
    monkeypatch.setattr(
        cloud_settings,
        "api_public_base_url",
        "",
    )

    reset_object_store_for_tests()

    response = api_client.post(
        "/cloud/storage/upload",
        headers=admin_headers,
        data={"prefix": "contract-tests"},
        files={
            "file": (
                "hello.txt",
                b"hello cloud storage",
                "text/plain",
            )
        },
    )

    data = assert_json_response(response)

    assert_ok_response(data)
    assert "object" in data

    stored = data["object"]

    assert stored["provider"] == "local"
    assert stored["size"] == len(b"hello cloud storage")
    assert stored["content_type"] == "text/plain"
    assert stored["key"].startswith("contract-tests/")
    assert stored["url"].startswith("/cloud-files/")

    stored_path = tmp_path / stored["key"]
    assert stored_path.exists()
    assert stored_path.read_bytes() == b"hello cloud storage"

    reset_object_store_for_tests()


def test_direct_upload_size_limit_contract(
    api_client,
    admin_headers,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        cloud_settings,
        "local_storage_root",
        str(tmp_path),
    )
    monkeypatch.setattr(
        cloud_settings,
        "storage_provider",
        "local",
    )
    monkeypatch.setattr(
        cloud_settings,
        "upload_max_bytes",
        4,
    )

    reset_object_store_for_tests()

    response = api_client.post(
        "/cloud/storage/upload",
        headers=admin_headers,
        files={
            "file": (
                "too-large.txt",
                b"12345",
                "text/plain",
            )
        },
    )

    data = assert_json_response(response, expected_status=413)

    assert_error_response(
        data,
        stage="upload_size_limit",
    )
    assert data["max_bytes"] == 4
    assert data["actual_bytes"] == 5

    reset_object_store_for_tests()


def test_presign_upload_is_unsupported_for_local_storage(
    api_client,
    admin_headers,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        cloud_settings,
        "storage_provider",
        "local",
    )
    monkeypatch.setattr(
        cloud_settings,
        "local_storage_root",
        str(tmp_path),
    )

    reset_object_store_for_tests()

    response = api_client.post(
        "/cloud/storage/presign-upload",
        headers=admin_headers,
        json={
            "filename": "avatar.png",
            "content_type": "image/png",
            "prefix": "contract-tests",
            "expires_seconds": 900,
        },
    )

    data = assert_json_response(response, expected_status=400)

    assert_error_response(
        data,
        stage="object_storage_unsupported",
    )
    assert "presigned upload" in data["error"]

    reset_object_store_for_tests()


def test_presign_upload_validation_contract(api_client, admin_headers):
    response = api_client.post(
        "/cloud/storage/presign-upload",
        headers=admin_headers,
        json={
            "filename": "",
            "content_type": "image/png",
            "prefix": "uploads",
            "expires_seconds": 900,
        },
    )

    data = assert_json_response(response, expected_status=422)

    assert data["ok"] is False
    assert data["stage"] == "cloud_validation"
    assert isinstance(data["error"], str)
    assert isinstance(data.get("request_id", ""), str)


@pytest.mark.parametrize("credential", ["missing", "user", "wrong-admin"])
@pytest.mark.parametrize("method,path,kwargs", [
    pytest.param("GET", "/cloud/ready", {}, id="ready"),
    pytest.param("GET", "/cloud/limits", {}, id="limits"),
    pytest.param("POST", "/cloud/storage/upload", {
        "files": {"file": ("blocked.txt", b"must-not-be-written", "text/plain")},
    }, id="upload"),
    pytest.param("POST", "/cloud/storage/presign-upload", {
        "json": {"filename": "blocked.png", "content_type": "image/png"},
    }, id="presign"),
    pytest.param("POST", "/cloud/storage/presign-upload", {
        "json": {"filename": ""},
    }, id="presign-invalid-body"),
])
def test_cloud_management_requires_admin_before_storage_or_validation(
    api_client, admin_headers, auth_headers, monkeypatch, credential, method, path, kwargs,
):
    from unittest.mock import AsyncMock, Mock

    from apps.api.routes import cloud

    store = Mock(side_effect=AssertionError("unauthorized_storage_access"))
    health = AsyncMock(side_effect=AssertionError("unauthorized_redis_access"))
    monkeypatch.setattr(cloud, "get_object_store", store)
    monkeypatch.setattr(cloud, "redis_health", health)

    headers = {
        "missing": {},
        "user": auth_headers("test-user"),
        "wrong-admin": {"X-Cloud-Admin-Token": "synthetic-wrong-admin-token"},
    }[credential]
    response = api_client.request(method, path, headers=headers, **kwargs)
    data = assert_json_response(response, expected_status=403)
    assert_error_response(data, stage="cloud_admin_auth")
    store.assert_not_called()
    health.assert_not_awaited()
