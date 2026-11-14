from __future__ import annotations

import json
from typing import Any

from fastapi import Response

from aiagent.services.generation_errors import GenerationUnavailableError
from apps.api.request_context import get_request_id
from apps.api.shared_state_errors import shared_state_error_response


def json_response(body: dict[str, Any], status_code: int = 200) -> Response:
    payload = dict(body)

    request_id = get_request_id()
    if request_id and "request_id" not in payload:
        payload["request_id"] = request_id

    return Response(
        content=json.dumps(payload, ensure_ascii=False, default=str),
        media_type="application/json; charset=utf-8",
        status_code=status_code,
    )


def ok_response(
    *,
    status_code: int = 200,
    **body: Any,
) -> Response:
    payload = {
        "ok": True,
        **body,
    }
    return json_response(payload, status_code=status_code)


def error_response(
    *, stage: str, exc: Exception, status_code: int = 500,
    runtime_error: str | None = None, include_traceback: bool = True,
    extra: dict[str, Any] | None = None,
) -> Response:
    del runtime_error, include_traceback
    shared_error = shared_state_error_response(exc)
    if shared_error is not None:
        return shared_error
    generation_failed = isinstance(exc, GenerationUnavailableError)
    if generation_failed:
        return json_response({
            "ok": False, "degraded": True, "stage": "llm_generation",
            "code": exc.code, "error": exc.code,
            "reply": "暂时无法生成回复，请稍后重试。",
            "base_reply_text": "", "should_speak": False, "should_store_memory": False,
            "audio_path": None, "audio_url": None,
            "audio_segments": [], "audio_segment_urls": [], "audio_segment_texts": [],
            "metadata": {"llm_inference": "failed", "llm_mock": "false"},
        }, status_code=503)
    # 普通用户接口不再回传任意异常正文、traceback 或 runtime 错误文本。
    payload = {"ok": False, "stage": stage, "error": "request_failed"}
    if extra:
        # 只保留无正文的诊断标识，不扩展为任意 metadata 回传。
        for key in ("call_id", "user_id", "memory_id"):
            if isinstance(extra.get(key), str):
                payload[key] = extra[key]
    return json_response(payload, status_code=status_code)


def error_message_response(
        *,
        stage:str,
        error:str,
        status_code: int = 400,
        extra:dict[str,Any]|None = None,
) ->Response:
    payload :dict[str,Any] = {
        "ok":False,
        "stage":stage,
        "error":error,
    }

    if extra:
        payload.update(extra)

    return json_response(payload,status_code=status_code)
