from pathlib import Path

import yaml


def test_backend_ci_initializes_headless_audio_before_portaudio_probe():
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "backend.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["backend"]
    steps = job["steps"]
    named_steps = {step["name"]: index for index, step in enumerate(steps) if "name" in step}

    install_index = named_steps["Install native audio runtime"]
    start_index = named_steps["Start headless PulseAudio server"]
    probe_index = named_steps["Verify PortAudio availability"]
    assert install_index < start_index < probe_index

    install = steps[install_index]["run"]
    for package in ("libportaudio2", "pulseaudio", "pulseaudio-utils"):
        assert package in install.split()

    start = steps[start_index]["run"]
    assert 'export PULSE_SERVER="unix:$pulse_dir/native"' in start
    assert "printf 'PULSE_SERVER=%s\\n' \"$PULSE_SERVER\" >> \"$GITHUB_ENV\"" in start
    assert 'install -d -m 700 "$pulse_dir"' in start
    assert "--exit-idle-time=-1" in start
    assert "--load=\"module-native-protocol-unix socket=$pulse_dir/native auth-anonymous=0\"" in start
    assert "module-null-sink sink_name=ci_null" in start
    assert "pactl info" in start
    assert "pactl set-default-sink ci_null" in start
    assert "pactl set-default-source ci_null.monitor" in start

    probe = steps[probe_index]
    assert "import sounddevice" in probe["run"]
    assert "get_portaudio_version()" in probe["run"]
    assert "|| true" not in probe["run"]
    assert not probe.get("continue-on-error", False)
