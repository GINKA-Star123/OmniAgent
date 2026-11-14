from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from apps.api.request_context import get_request_id

router = APIRouter()
logger = logging.getLogger("aiagent.api.telemetry")

# 受限测试期落本地 JSONL；后续可替换为对象存储/消息队列，接口不变。
TELEMETRY_DIR = Path("data/telemetry")
MAX_EVENTS_PER_BATCH = 200
_RECENT_BATCHES: OrderedDict[str, int] = OrderedDict()
_RECENT_BATCH_LIMIT = 2000


def _remember_batch(batch_id: str) -> bool:
    """进程内幂等：同一 batch_id 只入库一次（多进程场景仍需服务端存储去重）。"""
    if batch_id in _RECENT_BATCHES:
        return False
    _RECENT_BATCHES[batch_id] = int(time.time())
    while len(_RECENT_BATCHES) > _RECENT_BATCH_LIMIT:
        _RECENT_BATCHES.popitem(last=False)
    return True


class TelemetryApp(BaseModel):
    model_config = {"extra": "allow"}

    version: str = ""
    platform: str = ""
    os: str = ""


class TelemetryEvent(BaseModel):
    model_config = {"extra": "allow"}

    id: str = ""
    type: str = "unknown"
    ts: int = 0


class TelemetryBatchRequest(BaseModel):
    batch_id: str = Field(min_length=8, max_length=64)
    app: TelemetryApp = Field(default_factory=TelemetryApp)
    events: list[TelemetryEvent] = Field(default_factory=list)


@router.post("/telemetry/batch")
def submit_telemetry(req: TelemetryBatchRequest, request: Request):
    principal = getattr(request.state, "principal", None)
    user_id = getattr(principal, "user_id", "") or ""

    events = list(req.events[:MAX_EVENTS_PER_BATCH])
    truncated = len(req.events) > MAX_EVENTS_PER_BATCH
    accepted = 0
    duplicates = 0

    if _remember_batch(req.batch_id):
        record = {
            "received_at": int(time.time()),
            "user_id": user_id,
            "batch_id": req.batch_id,
            "app": req.app.model_dump(),
            "events": [event.model_dump() for event in events],
        }
        try:
            TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
            path = TELEMETRY_DIR / f"{time.strftime('%Y-%m-%d')}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            logger.exception("Telemetry write failed")
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "stage": "telemetry_write",
                    "error": "storage_unavailable",
                    "request_id": get_request_id(),
                },
            )
        accepted = len(events)
        logger.info(
            "telemetry batch user=%s batch=%s events=%d", user_id, req.batch_id, len(events)
        )
    else:
        duplicates = 1

    return {
        "ok": True,
        "accepted": accepted,
        "duplicates": duplicates,
        "truncated": truncated,
        "request_id": get_request_id(),
    }
