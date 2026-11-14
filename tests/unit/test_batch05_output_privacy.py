from __future__ import annotations

from unittest.mock import Mock

import pytest

from aiagent.expression.output_broadcaster import OutputBroadcaster
from aiagent.graphs.metadata_utils import now_perf
from aiagent.perception.voice_realtime_observability import (
    attach_voice_tts_status,
    mark_voice_stage_failed,
)
from aiagent.schemas.outputs import OutputEvent, ResponsePacket


@pytest.mark.parametrize(("component", "method", "metadata_key"), [
    ("motion_policy", "refine", "motion_policy"),
    ("tts_dispatcher", "dispatch", "tts"),
    ("live2d_dispatcher", "dispatch", "live2d"),
    ("audio_playback_dispatcher", "dispatch", "audio_playback"),
])
def test_broadcast_failures_do_not_expose_exception_body(component, method, metadata_key, caplog):
    canary = "CANARY_PRIVATE_PROVIDER_BODY"
    components = {name: Mock() for name in (
        "motion_policy", "tts_dispatcher", "live2d_dispatcher", "audio_playback_dispatcher",
    )}
    for name, item in components.items():
        getattr(item, "refine" if name == "motion_policy" else "dispatch").side_effect = lambda packet: packet
    getattr(components[component], method).side_effect = RuntimeError(canary)
    broadcaster = OutputBroadcaster(**components, enable_local_audio_playback=True)
    output = broadcaster.broadcast(OutputEvent(packet=ResponsePacket(reply_text="测试", should_speak=True)))
    assert output.packet.metadata[metadata_key].startswith("failed:")
    assert canary not in str(output.packet.metadata)
    assert canary not in caplog.text


def test_voice_error_metadata_uses_fixed_codes():
    canary = "CANARY_PRIVATE_PROVIDER_BODY"
    metadata = mark_voice_stage_failed({}, "turn", now_perf(), RuntimeError(canary))
    assert metadata["voice_turn_status"] == "failed"
    assert float(metadata["voice_turn_latency_ms"]) >= 0
    assert metadata["voice_turn_error"] == "voice_stage_failed"
    packet = ResponsePacket(reply_text="测试", metadata={"tts_status": "failed", "tts_error": canary})
    metadata = attach_voice_tts_status(metadata, packet=packet)
    assert metadata["voice_tts_error"] == "tts_generation_failed"
    assert canary not in str(metadata)
