from __future__ import annotations

import hashlib
import json
import shutil
from functools import lru_cache
from pathlib import Path
from threading import RLock
from uuid import uuid4

from aiagent.memory.approved_write import checked_id
from aiagent.state.redis_state_store import RedisStateStore
from aiagent.state.shared_state import SharedStateOwnershipError, SharedStateUnavailableError

PRIVATE_AUDIO_ROOT = Path("data/cache/private_audio").resolve()
_CLAIM = """
local old = redis.call('get', KEYS[1])
if old then
    if old ~= ARGV[1] then return 0 end
    return 1
end
redis.call('set', KEYS[1], ARGV[1])
return 1
"""
_CLAIM_MANY = """
for i, key in ipairs(KEYS) do
    local old = redis.call('get', key)
    if old and old ~= ARGV[i] then return 0 end
end
for i, key in ipairs(KEYS) do
    redis.call('set', key, ARGV[i])
end
return 1
"""

class PrivateResourceStore:
    def __init__(self, shared=None, *, local_limit: int = 10000) -> None:
        self.shared = shared
        self.local_limit = local_limit
        self._items : dict[str, str] = {}
        self._lock = RLock()

    def _key(self, kind: str, resource_id: str) -> str:
        digest = hashlib.sha256(f"{kind}\0{resource_id}".encode()).hexdigest()
        prefix = self.shared.prefix if self.shared is not None else "local"
        return f"{prefix}:v12:private-resource:{digest}"

    def register(self, kind: str, resource_id: str, user_id: str, path: str = "") -> None:
        checked_id(user_id)
        if not resource_id or kind not in {"audio", "output", "image"}:
            raise ValueError("private_resource_invalid")
        key = self._key(kind, resource_id)
        value = json.dumps({"user_id": user_id, "path": path}, sort_keys=True)
        if self.shared is not None:
            try:
                accepted = self.shared.redis.eval(_CLAIM, 1, key, value)
            except Exception:
                raise SharedStateUnavailableError("private_resource_backend_unavailable") from None
            if accepted != 1:
                raise SharedStateOwnershipError("private_resource_owner_conflict")
        else:
            with self._lock:
                existing = self._items.get(key)
                if existing is not None and existing != value:
                    raise SharedStateOwnershipError("private_resource_owner_conflict")
                if existing is None and len(self._items) >= self.local_limit:
                    raise SharedStateUnavailableError("private_resource_capacity_reached")
                self._items[key] = value

    def register_many(self, entries: list[tuple[str, str, str, str]]) -> None:
        """原子登记一份输出及其音频，冲突时不留下部分归属。"""
        records: dict[str, str] = {}
        for kind, resource_id, user_id, path in entries:
            checked_id(user_id)
            if not resource_id or kind not in {"audio", "output", "image"}:
                raise ValueError("private_resource_invalid")
            key = self._key(kind, resource_id)
            value = json.dumps({"user_id": user_id, "path": path}, sort_keys=True)
            if key in records and records[key] != value:
                raise SharedStateOwnershipError("private_resource_owner_conflict")
            records[key] = value
        if not records:
            return
        if self.shared is not None:
            try:
                accepted = self.shared.redis.eval(
                    _CLAIM_MANY, len(records), *records.keys(), *records.values(),
                )
            except Exception:
                raise SharedStateUnavailableError("private_resource_backend_unavailable") from None
            if accepted != 1:
                raise SharedStateOwnershipError("private_resource_owner_conflict")
            return
        with self._lock:
            for key, value in records.items():
                if key in self._items and self._items[key] != value:
                    raise SharedStateOwnershipError("private_resource_owner_conflict")
            if len(self._items.keys() | records.keys()) > self.local_limit:
                raise SharedStateUnavailableError("private_resource_capacity_reached")
            self._items.update(records)

    def owned(self, kind: str, resource_id: str, user_id: str) -> dict | None:
        key = self._key(kind, resource_id)
        if self.shared is not None:
            try:
                raw = self.shared.redis.get(key)
            except Exception:
                raise SharedStateUnavailableError("private_resource_backend_unavailable") from None
        else:
            with self._lock:
                raw = self._items.get(key)
        try:
            record = json.loads(raw) if raw else None
        except (ValueError, TypeError):
            raise SharedStateUnavailableError("private_resource_record_invalid") from None
        if raw is not None and (
            not isinstance(record, dict)
            or not isinstance(record.get("user_id"), str)
            or not isinstance(record.get("path"), str)
        ):
            raise SharedStateUnavailableError("private_resource_record_invalid")
        return record if isinstance(record, dict) and record.get("user_id") == user_id else None

@lru_cache(maxsize=1)
def get_private_resources() -> PrivateResourceStore:
    from cloud.config import cloud_settings

    if cloud_settings.execution_state_mode == "redis":
        shared = RedisStateStore(cloud_settings.redis_url, prefix=cloud_settings.redis_prefix)
        return PrivateResourceStore(shared)
    if cloud_settings.execution_state_mode != "local":
        raise SharedStateUnavailableError("private_resource_mode_invalid")
    from config.settings import settings

    if cloud_settings.cloud_mode or settings.app_env.lower() in {"prod", "production"}:
        raise SharedStateUnavailableError("cloud_private_resources_require_redis")
    return PrivateResourceStore()

def register_output_resources(output, *, user_id: str):
    resources = get_private_resources()
    packet = output.packet
    sources = list(packet.audio_segments) or ([packet.audio_path] if packet.audio_path else [])
    if not sources:
        resources.register("output", output.output_id, user_id)
        return output
    PRIVATE_AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    paths, urls, created = [], [], []
    entries = [("output", output.output_id, user_id, "")]
    try:
        for source_value in sources:
            source = Path(source_value).resolve()
            # Provider 产生的路径必须属于已知缓存，不读取任意系统文件。
            cache_root = Path("data/cache/tts_real").resolve()
            if not source.is_relative_to(cache_root) or not source.is_file():
                raise ValueError("tts_audio_path_invalid")
            if source.suffix.lower() not in {".wav", ".mp3", ".ogg"}:
                raise ValueError("tts_audio_type_invalid")
            filename = f"{uuid4().hex}{source.suffix.lower()}"
            target = PRIVATE_AUDIO_ROOT / filename
            created.append(target)
            shutil.copyfile(source, target)
            entries.append(("audio", filename, user_id, str(target)))
            paths.append(str(target))
            urls.append(f"/audio/{filename}")
        resources.register_many(entries)
    except Exception:
        for target in created:
            target.unlink(missing_ok=True)
        raise
    packet.audio_path, packet.audio_url = paths[0], urls[0]
    packet.audio_segments, packet.audio_segment_urls = paths, urls
    # 不修改 Live2D/Presence 契约。第五批不向其载荷传递新的下载 URL。
    return output
