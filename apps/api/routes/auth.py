from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from apps.api.auth_store import AuthError, get_auth_store
from apps.api.response_utils import json_response, ok_response
from config.settings import settings

router = APIRouter()
logger = logging.getLogger("aiagent.api.auth")


class RegisterRequest(BaseModel):
    username: str = ""
    password: str = ""
    invite_code: str = ""


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""


class GuestRequest(BaseModel):
    device_id: str = ""
    username: str = ""


def _error_response(exc: AuthError):
    return json_response(
        {
            "ok": False,
            "stage": "auth_" + exc.code,
            "error": exc.message,
            "code": exc.code,
        },
        status_code=exc.status,
    )


@router.post("/auth/register")
def register(req: RegisterRequest):
    try:
        record, token, expires_at = get_auth_store().register(
            req.username, req.password, req.invite_code
        )
    except AuthError as exc:
        return _error_response(exc)
    logger.info("auth register user=%s", record.user_id)
    return ok_response(
        user_id=record.user_id,
        username=record.username,
        token=token,
        expires_at=expires_at,
        is_guest=False,
    )


@router.post("/auth/login")
def login(req: LoginRequest):
    try:
        record, token, expires_at = get_auth_store().login(req.username, req.password)
    except AuthError as exc:
        return _error_response(exc)
    logger.info("auth login user=%s", record.user_id)
    return ok_response(
        user_id=record.user_id,
        username=record.username,
        token=token,
        expires_at=expires_at,
        is_guest=False,
    )


@router.post("/auth/guest")
def guest(req: GuestRequest):
    if not settings.auth_guest_enabled:
        return _error_response(AuthError("guest_disabled", 403, "guest access is disabled"))
    try:
        record, token, expires_at = get_auth_store().create_guest(req.device_id)
    except AuthError as exc:
        return _error_response(exc)
    logger.info("auth guest user=%s", record.user_id)
    return ok_response(
        user_id=record.user_id,
        username=record.username,
        token=token,
        expires_at=expires_at,
        is_guest=True,
    )


@router.get("/auth/me")
def me(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return json_response(
            {"ok": False, "stage": "auth_required", "error": "authentication required"},
            status_code=401,
        )
    record = get_auth_store().find_by_user_id(principal.user_id)
    return ok_response(
        user_id=principal.user_id,
        source=principal.source,
        username=record.username if record else "",
        is_guest=bool(record.is_guest) if record else False,
        created_at=record.created_at if record else 0,
    )
