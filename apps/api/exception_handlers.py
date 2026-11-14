from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response

from apps.api.response_utils import error_message_response


def _stage_from_path(path: str) -> str:
    if path.startswith("/cloud/tasks"):
        return "cloud_tasks"
    if path.startswith("/cloud/ops"):
        return "cloud_ops"
    if path.startswith("/cloud/gpu"):
        return "cloud_gpu"
    if path.startswith("/cloud"):
        return "cloud"
    if path.startswith("/voice/realtime"):
        # Auth failures happen before the route can set its operation-specific stage.
        operation = path.removeprefix("/voice/realtime/").partition("/")[0]
        if operation in {"start", "state", "turn", "interrupt", "end"}:
            return f"voice_realtime_{operation}"
        return "voice_realtime"
    if path.startswith("/voice"):
        return "voice"
    if path.startswith("/vision"):
        return "vision"
    if path.startswith("/knowledge"):
        return "knowledge"
    if path.startswith("/memory"):
        return "memory"
    return "http_exception"

async def http_exception_handler(request:Request, exc: HTTPException) -> Response:
    detail = exc.detail

    if isinstance(detail, dict):
        stage = str(detail.get("stage") or _stage_from_path(request.url.path))
        error = str(detail.get("error") or detail.get("detail") or exc.status_code)
        extra: dict[str, Any] = {
            str(key): value
            for key, value in detail.items()
            if key not in {"stage", "error", "detail"}
        }
    else:
        stage = _stage_from_path(request.url.path)
        error = str(detail)
        extra = {}

    response = error_message_response(
        stage=stage,
        error=error,
        status_code=exc.status_code,
        extra=extra,
    )
    for name, value in (exc.headers or {}).items():
        response.headers[name] = value
    return response

async def validation_exception_handler(request:Request, exc:RequestValidationError) -> Response:
    return error_message_response(
        stage = f"{_stage_from_path(request.url.path)}_validation",
        error = "request validation failed",
        status_code = 422,
        extra = {
            "detail": [
                {"type": item["type"], "loc": list(item["loc"])}
                for item in exc.errors()
            ],
        }
    )
