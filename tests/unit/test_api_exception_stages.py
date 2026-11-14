from __future__ import annotations

import pytest

from apps.api.exception_handlers import _stage_from_path


@pytest.mark.parametrize("path,expected", [
    ("/voice/realtime/start", "voice_realtime_start"),
    ("/voice/realtime/state/missing-call-id", "voice_realtime_state"),
    ("/voice/realtime/turn", "voice_realtime_turn"),
    ("/voice/realtime/interrupt", "voice_realtime_interrupt"),
    ("/voice/realtime/end", "voice_realtime_end"),
    ("/voice/realtime/end/", "voice_realtime_end"),
    ("/voice/realtime", "voice_realtime"),
    ("/voice/realtime/unknown", "voice_realtime"),
    ("/voice/realtime/turnover", "voice_realtime"),
    ("/voice/transcribe", "voice"),
    ("/vision/analyze", "vision"),
    ("/memory/user/u1", "memory"),
    ("/knowledge/search", "knowledge"),
    ("/cloud/tasks/example", "cloud_tasks"),
    ("/cloud/ops/example", "cloud_ops"),
    ("/cloud/gpu/example", "cloud_gpu"),
    ("/cloud/example", "cloud"),
    ("/chat", "http_exception"),
])
def test_exception_stage_preserves_operation_and_existing_fallbacks(path, expected):
    assert _stage_from_path(path) == expected
