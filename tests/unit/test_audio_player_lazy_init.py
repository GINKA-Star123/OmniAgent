from unittest.mock import Mock

import pytest

from integrations.audio import audio_player


def test_headless_runtime_construction_does_not_open_an_audio_device(monkeypatch):
    mixer = Mock()
    mixer.init.side_effect = RuntimeError("No audio device")
    monkeypatch.setattr(audio_player.pygame, "mixer", mixer)
    player = audio_player.AudioPlayer()
    assert not player.is_busy()
    player.stop(wait=True)
    mixer.init.assert_not_called()
    mixer.get_init.assert_not_called()


def test_real_playback_still_initializes_and_reports_device_failure(monkeypatch):
    mixer = Mock()
    mixer.get_init.return_value = None
    mixer.init.side_effect = RuntimeError("No audio device")
    monkeypatch.setattr(audio_player.pygame, "mixer", mixer)
    player = audio_player.AudioPlayer()
    with pytest.raises(RuntimeError, match="No audio device"):
        player.play("unused.wav")
    mixer.init.assert_called_once()
    assert not player._mixer_ready
