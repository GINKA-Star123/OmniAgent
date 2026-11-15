# tests/api/test_telemetry_summary_contract.py
from __future__ import annotations

import json

import pytest


@pytest.fixture()
def telemetry_dir(tmp_path, monkeypatch):
    from apps.api.routes import telemetry

    monkeypatch.setattr(telemetry, "TELEMETRY_DIR", tmp_path)
    return tmp_path


def _write(path, records) -> None:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def test_summary_aggregates_turns_and_feedback(api_client, admin_headers, telemetry_dir):
    path = telemetry_dir / "2026-01-02.jsonl"
    _write(
        path,
        [
            {
                "batch_id": "b1",
                "user_id": "user-a",
                "app": {"version": "1.3.0"},
                "events": [
                    {"type": "turn", "latency_ms": 100, "degraded": False},
                    {"type": "turn", "latency_ms": 300, "degraded": True},
                ],
            },
            {
                "batch_id": "b2",
                "user_id": "user-b",
                "app": {"version": "1.3.0"},
                "events": [
                    {"type": "turn", "latency_ms": 2000, "degraded": False},
                    {"type": "feedback", "rating": 1, "tags": []},
                    {"type": "feedback", "rating": -1, "tags": ["太慢", "太慢"]},
                ],
            },
        ],
    )

    response = api_client.get(
        "/telemetry/summary",
        params={"date": "2026-01-02"},
        headers=admin_headers,
    )
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["batches"] == 2
    assert data["events"] == 5
    assert data["turns"] == 3
    assert data["feedback"] == 2
    assert data["degraded"] == 1
    assert data["degraded_rate"] == 0.3333
    assert data["latency_ms"]["count"] == 3
    assert data["latency_ms"]["p50"] == 300.0
    assert data["latency_ms"]["p95"] == 2000.0
    assert data["ratings"] == {"up": 1, "down": 1}
    assert data["tags"]["太慢"] == 2


def test_summary_rejects_invalid_date(api_client, admin_headers, telemetry_dir):
    response = api_client.get(
        "/telemetry/summary",
        params={"date": "../etc/passwd"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_summary_requires_admin(api_client, telemetry_dir):
    response = api_client.get("/telemetry/summary")
    assert response.status_code in {401, 403, 503}
