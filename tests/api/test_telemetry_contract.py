# tests/api/test_telemetry_contract.py
from __future__ import annotations

import json

from apps.api.routes import telemetry as telemetry_module
from config.settings import settings


def _payload(batch_id: str, count: int = 2) -> dict:
    return {
        "batch_id": batch_id,
        "app": {"version": "1.3.0", "platform": "android", "os": "14"},
        "events": [
            {
                "id": f"evt-{index}",
                "type": "turn",
                "ts": 1730000000 + index,
                "client_message_id": f"msg-{index}",
                "latency_ms": 900 + index,
                "status": 200,
                "degraded": False,
                "text_len": 12,
            }
            for index in range(count)
        ],
    }


def test_telemetry_batch_writes_jsonl(api_client, tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry_module, "TELEMETRY_DIR", tmp_path)
    telemetry_module._RECENT_BATCHES.clear()

    response = api_client.post("/telemetry/batch", json=_payload("batch-0001"))
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["accepted"] == 2
    assert data["duplicates"] == 0

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    line = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
    assert line["batch_id"] == "batch-0001"
    assert line["user_id"] == settings.api_local_principal
    assert len(line["events"]) == 2
    assert line["app"]["platform"] == "android"


def test_telemetry_batch_is_idempotent(api_client, tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry_module, "TELEMETRY_DIR", tmp_path)
    telemetry_module._RECENT_BATCHES.clear()

    api_client.post("/telemetry/batch", json=_payload("batch-0002"))
    response = api_client.post("/telemetry/batch", json=_payload("batch-0002"))
    data = response.json()

    assert data["accepted"] == 0
    assert data["duplicates"] == 1
    assert len(list(tmp_path.glob("*.jsonl"))[0].read_text(encoding="utf-8").splitlines()) == 1


def test_telemetry_batch_validates_batch_id(api_client):
    response = api_client.post("/telemetry/batch", json={"batch_id": "x", "events": []})
    assert response.status_code == 422


def test_telemetry_batch_truncates_oversized_payload(api_client, tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry_module, "TELEMETRY_DIR", tmp_path)
    telemetry_module._RECENT_BATCHES.clear()

    response = api_client.post("/telemetry/batch", json=_payload("batch-0003", count=260))
    data = response.json()

    assert data["ok"] is True
    assert data["accepted"] == telemetry_module.MAX_EVENTS_PER_BATCH
    assert data["truncated"] is True
