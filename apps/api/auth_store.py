from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import settings

PBKDF2_ITERATIONS = 210_000
TOKEN_BYTES = 32
PASSWORD_MIN = 6
PASSWORD_MAX = 128
USERNAME_RE = re.compile(r"^\S{2,32}$")


class AuthError(Exception):
    """带 HTTP 语义的账号错误，路由层直接映射成响应。"""

    def __init__(self, code: str, status: int = 400, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.status = status
        self.message = message or code


@dataclass(frozen=True, slots=True)
class UserRecord:
    user_id: str
    username: str
    password_salt: str
    password_hash: str
    is_guest: bool
    created_at: int

    def to_json(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "password_salt": self.password_salt,
            "password_hash": self.password_hash,
            "is_guest": self.is_guest,
            "created_at": self.created_at,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> UserRecord:
        return cls(
            user_id=str(raw.get("user_id") or ""),
            username=str(raw.get("username") or ""),
            password_salt=str(raw.get("password_salt") or ""),
            password_hash=str(raw.get("password_hash") or ""),
            is_guest=bool(raw.get("is_guest")),
            created_at=int(raw.get("created_at") or 0),
        )


def _hash_password(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PBKDF2_ITERATIONS,
    ).hex()


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or not (PASSWORD_MIN <= len(password) <= PASSWORD_MAX):
        raise AuthError(
            "invalid_password",
            400,
            f"password length must be {PASSWORD_MIN}-{PASSWORD_MAX}",
        )


def _validate_username(username: str) -> str:
    name = str(username or "").strip()
    if not USERNAME_RE.fullmatch(name):
        raise AuthError("invalid_username", 400, "username must be 2-32 non-space chars")
    return name


class AuthStore:
    """单文件 JSON 账号/令牌存储（适合单 Worker 内测；多 Worker 需换 Redis/DB）。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] | None = None

    # ---------------- 存储 ----------------
    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"version": 1, "users": {}, "tokens": {}}

    def _load(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data
        data = self._empty()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data["version"] = int(raw.get("version") or 1)
                if isinstance(raw.get("users"), dict):
                    data["users"] = raw["users"]
                if isinstance(raw.get("tokens"), dict):
                    data["tokens"] = raw["tokens"]
        except (OSError, ValueError):
            data = self._empty()
        self._data = data
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def reset(self) -> None:
        self._data = None

    # ---------------- 令牌 ----------------
    def _issue(self, data: dict[str, Any], user_id: str, ttl_hours: int) -> tuple[str, int]:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        expires_at = int(time.time() + max(ttl_hours, 1) * 3600)
        data["tokens"][digest] = {"user_id": user_id, "expires_at": expires_at}
        return token, expires_at

    def token_map(self) -> dict[str, str]:
        """返回未过期 token 的 sha256 -> user_id；顺带清理过期项。"""
        now = int(time.time())
        with self._lock:
            data = self._load()
            expired = [
                digest
                for digest, item in data["tokens"].items()
                if int((item or {}).get("expires_at") or 0) <= now
            ]
            if expired:
                for digest in expired:
                    data["tokens"].pop(digest, None)
                self._save(data)
            return {
                digest: str((item or {}).get("user_id") or "")
                for digest, item in data["tokens"].items()
                if str((item or {}).get("user_id") or "")
            }

    # ---------------- 账号 ----------------
    def register(
        self,
        username: str,
        password: str,
        invite_code: str = "",
    ) -> tuple[UserRecord, str, int]:
        if not settings.auth_registration_enabled:
            raise AuthError("registration_disabled", 403, "registration is disabled")
        expected_invite = settings.auth_invite_code.strip()
        if expected_invite and not hmac.compare_digest(
            str(invite_code or "").strip(), expected_invite
        ):
            raise AuthError("invalid_invite", 403, "invite code is invalid")

        name = _validate_username(username)
        _validate_password(password)
        key = name.lower()

        with self._lock:
            data = self._load()
            if key in data["users"]:
                raise AuthError("username_taken", 409, "username already exists")
            salt = secrets.token_hex(16)
            record = UserRecord(
                user_id="user-" + secrets.token_hex(8),
                username=name,
                password_salt=salt,
                password_hash=_hash_password(password, salt),
                is_guest=False,
                created_at=int(time.time()),
            )
            data["users"][key] = record.to_json()
            token, expires_at = self._issue(
                data, record.user_id, settings.auth_token_ttl_hours
            )
            self._save(data)
            return record, token, expires_at

    def login(self, username: str, password: str) -> tuple[UserRecord, str, int]:
        key = str(username or "").strip().lower()
        with self._lock:
            data = self._load()
            raw = data["users"].get(key)
            if not isinstance(raw, dict):
                raise AuthError("invalid_credentials", 401, "wrong username or password")
            record = UserRecord.from_json(raw)
            if record.is_guest or not record.password_salt:
                raise AuthError("invalid_credentials", 401, "guest account cannot login")
            candidate = _hash_password(str(password or ""), record.password_salt)
            if not hmac.compare_digest(candidate, record.password_hash):
                raise AuthError("invalid_credentials", 401, "wrong username or password")
            token, expires_at = self._issue(
                data, record.user_id, settings.auth_token_ttl_hours
            )
            self._save(data)
            return record, token, expires_at

    def create_guest(self, device_id: str = "") -> tuple[UserRecord, str, int]:
        if not settings.auth_guest_enabled:
            raise AuthError("guest_disabled", 403, "guest access is disabled")
        with self._lock:
            data = self._load()
            suffix = secrets.token_hex(6)
            record = UserRecord(
                user_id="guest-" + suffix,
                username="游客" + suffix[-4:],
                password_salt="",
                password_hash="",
                is_guest=True,
                created_at=int(time.time()),
            )
            # 游客也登记到 users，便于 /auth/me 查询；key 用 user_id 避免与用户名冲突。
            data["users"]["guest:" + record.user_id] = record.to_json()
            token, expires_at = self._issue(
                data, record.user_id, settings.auth_guest_token_ttl_hours
            )
            self._save(data)
            return record, token, expires_at

    def find_by_user_id(self, user_id: str) -> UserRecord | None:
        with self._lock:
            data = self._load()
            for raw in data["users"].values():
                if isinstance(raw, dict) and raw.get("user_id") == user_id:
                    return UserRecord.from_json(raw)
        return None


_stores: dict[str, AuthStore] = {}
_stores_lock = threading.Lock()


def get_auth_store() -> AuthStore:
    path = Path(settings.auth_store_path)
    key = str(path.expanduser().resolve())
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            store = AuthStore(path)
            _stores[key] = store
        return store


def reset_auth_store() -> None:
    """测试/换配置时清空单例缓存。"""
    with _stores_lock:
        for store in _stores.values():
            store.reset()
        _stores.clear()
