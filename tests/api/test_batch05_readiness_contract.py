from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from apps.api import user_auth
from apps.api.routes import health
from cloud.readiness import ReadinessCheck, ReadinessSnapshot, ReadinessStatus


def _snapshot(ok: bool) -> ReadinessSnapshot:
    return ReadinessSnapshot(
        ok=ok,
        status=ReadinessStatus.READY if ok else ReadinessStatus.NOT_READY,
        checks={"example_dependency": ok},
        summary={"total": 1, "required_failed": 0 if ok else 1, "optional_failed": 0},
        items=[ReadinessCheck(
            name="example_dependency",
            ok=ok,
            required=True,
            summary="available" if ok else "unavailable",
            action="secret-action-canary",
            details={"private": "secret-detail-canary"},
        )],
        cloud_mode=True,
        details={"private": "secret-detail-canary"},
    )


@pytest.fixture
def client(monkeypatch):
    async def admin_denied(*args, **kwargs):
        raise HTTPException(status_code=403, detail="admin_required")

    monkeypatch.setattr("apps.api.user_auth.require_cloud_admin", admin_denied)
    app = FastAPI(dependencies=[Depends(user_auth.enforce_http_policy)])
    app.include_router(health.router)

    @app.get("/protected-example")
    def protected_example():
        return {"ok": True}

    with TestClient(app) as value:
        yield value


@pytest.mark.parametrize(("ok", "status"), [(True, 200), (False, 503)])
def test_readiness_status_and_redaction(client, monkeypatch, ok, status):
    async def fake_readiness():
        return _snapshot(ok)

    monkeypatch.setattr(health, "build_public_readiness", fake_readiness)
    response = client.get("/ready")
    assert response.status_code == status
    assert response.json()["ok"] is ok
    assert response.json()["details"] == {}
    assert "secret-detail-canary" not in response.text
    assert "secret-action-canary" not in response.text


def test_public_liveness_and_default_admin_contrast(client):
    assert client.get("/live").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/protected-example").status_code == 403
