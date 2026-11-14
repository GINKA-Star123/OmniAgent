from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass

from fastapi import HTTPException, Request

from aiagent.memory.approved_write import checked_id
from cloud.admin_auth import require_cloud_admin
from cloud.config import cloud_settings
from config.settings import settings

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43,256}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_USER_INPUTS = {
    ("POST", "/chat"), ("POST", "/chat/multimodal"),
    ("POST", "/vision/analyze"), ("POST", "/vision/chat"),
    ("POST", "/session/open"), ("POST", "/voice/realtime/start"),
    ("POST", "/voice/realtime/turn"),
}
_CALL_INPUTS = {
    ("POST", "/voice/realtime/end"), ("POST", "/voice/realtime/interrupt"),
    ("POST", "/voice/realtime/turn"),
    ("GET", "/voice/realtime/state/{call_id}"),
}
_USER_READS = {("POST", "/voice/transcribe"), ("GET", "/vision/schema"),
               ("GET", "/audio/{filename}")}
# 遥测上报：只要求有效凭据，body 里没有 user_id 字段。
_USER_EVENTS = {("POST", "/telemetry/batch")}
_PUBLIC = {("GET", "/"), ("GET", "/live"), ("GET", "/health"), ("GET", "/ready")}


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    source: str


def token_map() -> dict[str, str]:
    try:
        mapping = json.loads(settings.api_auth_token_sha256_map)
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError()
        for digest, user_id in mapping.items():
            if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
                raise ValueError()
            checked_id(user_id)
        return mapping
    except (ValueError, TypeError):
        raise RuntimeError("api_auth_configuration_invalid") from None


def validate_auth_config() -> None:
    mode = settings.api_auth_mode
    production = cloud_settings.cloud_mode or settings.app_env.lower() in {"production", "prod"}
    if mode not in {"bearer", "local-dev"}:
        raise RuntimeError("api_auth_mode_invalid")
    if mode == "local-dev":
        if production:
            raise RuntimeError("local_dev_auth_forbidden_in_production")
        checked_id(settings.api_local_principal)
    else:
        token_map()
        if settings.enable_local_audio_playback:
            raise RuntimeError("multiuser_http_requires_client_audio_playback")
    if production and cloud_settings.execution_state_mode != "redis":
        raise RuntimeError("production_private_resources_require_redis")
    if production and (
        cloud_settings.voice_call_store_provider == "memory"
        or cloud_settings.voice_call_store_fail_open
    ):
        raise RuntimeError("production_voice_call_store_requires_fail_closed_redis")


def authenticate(request: Request) -> Principal:
    try:
        validate_auth_config()
    except (RuntimeError, ValueError):
        raise HTTPException(503, detail={"code": "auth_configuration_unavailable"}) from None
    if settings.api_auth_mode == "local-dev":
        return Principal(settings.api_local_principal, "local-dev")
    authorization = request.headers.getlist("authorization")
    if len(authorization) != 1:
        raise HTTPException(401, detail={"code": "authentication_required"},
                            headers={"WWW-Authenticate": "Bearer"})
    pieces = authorization[0].split(" ")
    if len(pieces) != 2 or pieces[0].lower() != "bearer" or not _TOKEN.fullmatch(pieces[1]):
        raise HTTPException(401, detail={"code": "invalid_credentials"},
                            headers={"WWW-Authenticate": "Bearer"})
    digest = hashlib.sha256(pieces[1].encode("ascii")).hexdigest()
    for expected, user_id in token_map().items():
        if hmac.compare_digest(digest, expected):
            return Principal(user_id, "bearer")
    raise HTTPException(401, detail={"code": "invalid_credentials"},
                        headers={"WWW-Authenticate": "Bearer"})


async def _body_fields(request: Request) -> dict:
    if request.method in {"GET", "HEAD"}:
        return {}
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type == "application/json":
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, detail={"code": "invalid_json"}) from None
        if not isinstance(body, dict):
            raise HTTPException(400, detail={"code": "object_body_required"})
        return body
    if content_type in {"multipart/form-data", "application/x-www-form-urlencoded"}:
        form = await request.form()
        for field in ("user_id", "call_id"):
            if len(form.getlist(field)) > 1:
                raise HTTPException(400, detail={"code": "duplicate_identity_field"})
        return dict(form)
    return {}


async def enforce_http_policy(request: Request) -> None:
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    key = (request.method, path)
    if key in _PUBLIC:
        return
    user_memory = path.startswith("/memory/user/{user_id}")
    user_route = (
        key in _USER_INPUTS | _CALL_INPUTS | _USER_READS | _USER_EVENTS or user_memory
    )
    if not user_route:
        # 未明确列入用户面的现有/新增路径默认属于管理面。
        await require_cloud_admin(
            request.headers.get("x-cloud-admin-token"),
            request.headers.get("x-admin-token"),
        )
        return
    principal = authenticate(request)
    request.state.principal = principal
    fields = await _body_fields(request)
    declared = request.path_params.get("user_id") if user_memory else fields.get("user_id")
    if user_memory or key in _USER_INPUTS:
        if not isinstance(declared, str) or declared != principal.user_id:
            raise HTTPException(403, detail={"code": "principal_mismatch"})
    if key in _CALL_INPUTS:
        from apps.api.routes.voice_realtime import _CALL_STORE

        call_id = request.path_params.get("call_id") or fields.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise HTTPException(400, detail={"code": "call_id_required"})
        call = await _CALL_STORE.get(call_id, touch=False)
        if call is None or call.user_id != principal.user_id:
            raise HTTPException(404, detail={"code": "call_not_found"})
