"""Manage sessions, rooms, and runtime contexts."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from aiagent.schemas.inputs import InputEvent

# 兼容旧客户端：允许通过 InputEvent.metadata 传递会话/回合标识
SESSION_METADATA_KEY = "session_id"
TURN_METADATA_KEY = "turn_id"

class SessionManager:
    def resolve_session_id(self, event: InputEvent) -> str:
        user = event.user_id.strip()
        if not user:
            raise ValueError("session_owner_required")
        logical = (
            (event.session_id or "").strip()
            or str(event.metadata.get(SESSION_METADATA_KEY) or "").strip()
            or f"{event.source}:{user}"
        )
        digest = hashlib.sha256(json.dumps([user, logical], ensure_ascii=False,
                                          separators=(",", ":")).encode()).hexdigest()
        return f"s12:{digest}"


    def resolve_turn_id(self, event: InputEvent, *, session_id: str) -> str:
        """
        解析回合 id,格式 ``{session_id}:{short_uuid}``

        语义上与 request_id(HTTP 请求),event_id(输入事件)区分开；
        显式传入时以传入值为准——语音链路会传 ``{call_id}:{turn_count}``
        """

        explicit = (event.turn_id or "").strip()

        if explicit:
            return explicit

        from_metadata = str(event.metadata.get(TURN_METADATA_KEY, "")or "").strip()

        if from_metadata:
            return from_metadata

        return f"{session_id}:{str(uuid4())[:8]}"
