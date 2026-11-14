from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from aiagent.schemas.outputs import OutputEvent, ResponsePacket
from aiagent.state import private_resources as module
from aiagent.state.private_resources import PrivateResourceStore
from aiagent.state.shared_state import SharedStateOwnershipError, SharedStateUnavailableError


class FakeRedis:
    def __init__(self):
        self.items, self.broken = {}, False

    def eval(self, script, count, *args):
        if self.broken:
            raise ConnectionError("CANARY_REDIS_ERROR")
        pairs = list(zip(args[:count], args[count:], strict=True))
        for key, value in pairs:
            if key in self.items and self.items[key] != value:
                return 0
        self.items.update(pairs)
        return 1

    def get(self, key):
        if self.broken:
            raise ConnectionError("CANARY_REDIS_ERROR")
        return self.items.get(key)


@pytest.fixture(params=["local", "redis-adapter", "real-redis"])
def resources(request):
    if request.param == "local":
        yield PrivateResourceStore()
    elif request.param == "redis-adapter":
        yield PrivateResourceStore(SimpleNamespace(prefix="test", redis=FakeRedis()))
    else:
        url = os.environ.get("BATCH05_REDIS_URL")
        if not url:
            pytest.skip("explicit BATCH05_REDIS_URL required for real Redis contract")
        from aiagent.state.redis_state_store import RedisStateStore

        prefix = f"batch05-contract:{uuid4().hex}"
        shared = RedisStateStore(url, prefix=prefix)
        try:
            yield PrivateResourceStore(shared)
        finally:
            # 只清理本用例随机前缀，不触及业务状态。
            keys = list(shared.redis.scan_iter(match=f"{prefix}:v12:private-resource:*"))
            if keys:
                shared.redis.delete(*keys)
            shared.redis.close()


def test_owner_contract_identical_for_local_and_redis(resources):
    resources.register("audio", "a.wav", "u1", "/not-served-by-this-test/a.wav")
    assert resources.owned("audio", "a.wav", "u1") is not None
    assert resources.owned("audio", "a.wav", "u2") is None
    assert resources.owned("audio", "missing.wav", "u1") is None
    with pytest.raises(SharedStateOwnershipError):
        resources.register("audio", "a.wav", "u2", "/other/a.wav")
    assert resources.owned("audio", "a.wav", "u1")["user_id"] == "u1"
    resources.register("output", "output-1", "u1")
    assert resources.owned("output", "output-1", "u2") is None


def test_redis_failure_never_falls_back_to_memory():
    redis = FakeRedis()
    resources = PrivateResourceStore(SimpleNamespace(prefix="test", redis=redis))
    redis.broken = True
    with pytest.raises(SharedStateUnavailableError, match="private_resource_backend_unavailable"):
        resources.register("audio", "a.wav", "u1")
    with pytest.raises(SharedStateUnavailableError):
        resources.owned("audio", "a.wav", "u1")
    assert not resources._items


def test_local_capacity_is_bounded():
    resources = PrivateResourceStore(local_limit=1)
    resources.register("output", "one", "u1")
    with pytest.raises(SharedStateUnavailableError, match="capacity_reached"):
        resources.register("output", "two", "u1")


def test_batch_owner_registration_is_atomic_on_conflict(resources):
    resources.register("output", "existing", "u2")
    with pytest.raises(SharedStateOwnershipError):
        resources.register_many([
            ("audio", "new.wav", "u1", "/synthetic/new.wav"),
            ("output", "existing", "u1", ""),
        ])
    assert resources.owned("audio", "new.wav", "u1") is None
    assert resources.owned("output", "existing", "u2") is not None


def test_batch_owner_registration_success(resources):
    resources.register_many([
        ("output", "batch-output", "u1", ""),
        ("audio", "batch.wav", "u1", "/synthetic/batch.wav"),
    ])
    assert resources.owned("output", "batch-output", "u1")
    assert resources.owned("audio", "batch.wav", "u1")


def test_local_batch_capacity_failure_has_no_partial_registration():
    resources = PrivateResourceStore(local_limit=1)
    with pytest.raises(SharedStateUnavailableError, match="capacity_reached"):
        resources.register_many([
            ("output", "one", "u1", ""),
            ("audio", "two.wav", "u1", "/synthetic/two.wav"),
        ])
    assert not resources._items


def test_same_source_audio_gets_separate_owner_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    private_root = tmp_path / "data/cache/private_audio"
    monkeypatch.setattr(module, "PRIVATE_AUDIO_ROOT", private_root)
    resources = PrivateResourceStore()
    monkeypatch.setattr(module, "get_private_resources", lambda: resources)
    source = tmp_path / "data/cache/tts_real/shared.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"same-synthetic-audio")
    def output():
        return OutputEvent(packet=ResponsePacket(reply_text="回答", audio_path=str(source),
                           audio_segments=[str(source)], audio_segment_texts=["回答"]))
    first = module.register_output_resources(output(), user_id="u1")
    second = module.register_output_resources(output(), user_id="u2")
    assert first.packet.audio_url != second.packet.audio_url
    filename = first.packet.audio_url.rsplit("/", 1)[1]
    assert resources.owned("audio", filename, "u1")
    assert resources.owned("audio", filename, "u2") is None
    assert resources.owned("output", first.output_id, "u2") is None


def test_source_outside_cache_is_not_published(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    resources = PrivateResourceStore()
    monkeypatch.setattr(module, "get_private_resources", lambda: resources)
    monkeypatch.setattr(module, "PRIVATE_AUDIO_ROOT", tmp_path / "data/cache/private_audio")
    source = tmp_path / "system-secret.wav"
    source.write_bytes(b"secret")
    output = OutputEvent(packet=ResponsePacket(reply_text="回答", audio_path=str(source)))
    with pytest.raises(ValueError, match="tts_audio_path_invalid"):
        module.register_output_resources(output, user_id="u1")
    assert not resources._items


def test_later_audio_copy_failure_cleans_files_and_owners(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data/cache/private_audio"
    monkeypatch.setattr(module, "PRIVATE_AUDIO_ROOT", root)
    resources = PrivateResourceStore()
    monkeypatch.setattr(module, "get_private_resources", lambda: resources)
    source = tmp_path / "data/cache/tts_real/first.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic-audio")
    output = OutputEvent(packet=ResponsePacket(
        reply_text="测试", audio_segments=[str(source), str(source.parent / "missing.wav")],
    ))
    with pytest.raises(ValueError, match="tts_audio_path_invalid"):
        module.register_output_resources(output, user_id="u1")
    assert not resources._items
    assert list(root.iterdir()) == []


def test_owner_registration_failure_cleans_copied_audio(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data/cache/private_audio"
    monkeypatch.setattr(module, "PRIVATE_AUDIO_ROOT", root)
    resources = PrivateResourceStore(local_limit=1)
    monkeypatch.setattr(module, "get_private_resources", lambda: resources)
    source = tmp_path / "data/cache/tts_real/source.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic-audio")
    output = OutputEvent(packet=ResponsePacket(reply_text="测试", audio_path=str(source)))
    with pytest.raises(SharedStateUnavailableError, match="capacity_reached"):
        module.register_output_resources(output, user_id="u1")
    assert not resources._items
    assert list(root.iterdir()) == []
