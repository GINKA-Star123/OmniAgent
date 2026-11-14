from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from aiagent.memory.memory_layers import infer_memory_layer
from aiagent.memory.memory_safety import MemorySafetyFilter
from aiagent.schemas.memory import MemoryCategory, MemoryImportance, MemoryStorePlan

_PROCESS_KEY = secrets.token_bytes(32)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}\Z")
_SOURCES = {"chat_turn", "user_edit", "user_merge"}

class ApprovalError(ValueError):
    def __init__(self) -> None:
        super().__init__("memory_approval_invalid")

def checked_id(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ApprovalError()
    return value

def scope_digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

@dataclass(frozen=True, slots=True)
class ApprovedMemoryWrite:
    user_id: str
    agent_id: str
    text: str
    category: str
    importance: str
    source: str
    session_ref: str
    turn_ref: str
    created_at: str
    signature: str = ""
def _unsigned(payload: ApprovedMemoryWrite) -> bytes:
    data = asdict(payload)
    data.pop("signature")
    return json.dumps(data, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")

def approve_plan(
        plan: MemoryStorePlan,
        *,
        user_id: str,
        agent_id: str,
        session_id: str = "",
        turn_id: str = "",
) -> ApprovedMemoryWrite:
    if not (
        plan.should_store and plan.status == "ready" and plan.guard.allowed
        and not plan.dedup.duplicate
        and plan.memory_text == plan.guard.redacted_text
    ):
        raise ApprovalError()

    text = plan.memory_text.strip()
    guard = MemorySafetyFilter().evaluate(text)
    if not guard.allowed or guard.redacted_text != text or not 1 <= len(text) <= 2000:
        raise ApprovalError()
    if plan.source not in _SOURCES:
        raise ApprovalError()
    payload = ApprovedMemoryWrite(
        user_id=checked_id(user_id), agent_id=checked_id(agent_id), text=text,
        category=MemoryCategory(plan.category).value,
        importance=MemoryImportance(plan.importance).value,
        source=plan.source,
        session_ref=scope_digest(session_id), turn_ref=scope_digest(turn_id),
        created_at=datetime.now(UTC).isoformat(),
    )
    signature = hmac.new(_PROCESS_KEY, _unsigned(payload), hashlib.sha256).hexdigest()
    return ApprovedMemoryWrite(**{**asdict(payload), "signature": signature})

def verify_approved(payload: ApprovedMemoryWrite) -> None:
    if not isinstance(payload, ApprovedMemoryWrite):
        raise ApprovalError()
    checked_id(payload.user_id)
    checked_id(payload.agent_id)
    expected = hmac.new(_PROCESS_KEY, _unsigned(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, payload.signature):
        raise ApprovalError()
    guard = MemorySafetyFilter().evaluate(payload.text)
    if not guard.allowed or guard.redacted_text != payload.text:
        raise ApprovalError()

def approved_metadata(payload: ApprovedMemoryWrite) -> dict[str, str]:
    verify_approved(payload)
    return {
        "approval_version": "v12-b05",
        "approved_digest": hashlib.sha256(_unsigned(payload)).hexdigest(),
        "category": payload.category,
        "importance": payload.importance,
        "memory_layer": infer_memory_layer(MemoryCategory(payload.category)).value,
        "source": payload.source,
        "session_ref": payload.session_ref,
        "turn_ref": payload.turn_ref,
        "created_at": payload.created_at,
    }
