import pytest

from scripts import check_config_sync as sync


@pytest.mark.parametrize("relative,expected", [
    ("apps/api/probe.py", True),
    ("tests/probe.py", False),
    (".github/probe.py", False),
    ("apps/api/__pycache__/probe.py", False),
    (".venv/Lib/site-packages/probe.py", False),
    ("apps/desktop_qt/.venv-build/Lib/site-packages/probe.py", False),
    ("apps/api/venv/Lib/site-packages/probe.py", False),
    ("apps/api/build/probe.py", False),
    ("apps/api/dist/probe.py", False),
    ("third_party/probe.py", False),
])
def test_scan_scope_contrast(tmp_path, monkeypatch, relative, expected):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('os.getenv("SYNTHETIC_CONFIG_KEY")\n', encoding="utf-8")
    monkeypatch.setattr(sync, "PROJECT_ROOT", tmp_path)
    assert ("SYNTHETIC_CONFIG_KEY" in sync.collect_scanned_env()) is expected


@pytest.mark.parametrize(("relative", "content"), [
    ("aiagent/evaluation/probe.py", 'os.environ.get("SYNTHETIC_CONFIG_KEY")\n'),
    ("scripts/probe.ps1", "$env:SYNTHETIC_CONFIG_KEY\n"),
    ("deploy/probe.yml", "value: ${SYNTHETIC_CONFIG_KEY}\n"),
    ("deploy/probe.yaml", "value: ${SYNTHETIC_CONFIG_KEY}\n"),
])
def test_scan_keeps_supported_project_sources(tmp_path, monkeypatch, relative, content):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(sync, "PROJECT_ROOT", tmp_path)

    assert sync.collect_scanned_env() == {"SYNTHETIC_CONFIG_KEY": relative}


@pytest.mark.parametrize("system_key", ["TMP", "TEMP", "NUITKA_CACHE_DIR"])
def test_build_tool_environment_does_not_require_application_config(tmp_path, monkeypatch, system_key):
    monkeypatch.setattr(sync, "collect_settings_env", dict)
    monkeypatch.setattr(sync, "collect_scanned_env", lambda: {system_key: "packaging/build.ps1"})
    for name in ("ENV_EXAMPLE", "CLOUD_ENV_EXAMPLE", "CONFIG_REFERENCE"):
        path = tmp_path / name
        path.write_text("", encoding="utf-8")
        monkeypatch.setattr(sync, name, path)

    assert sync.main([]) == 0


@pytest.mark.parametrize("missing", [None, "ENV_EXAMPLE", "CLOUD_ENV_EXAMPLE", "CONFIG_REFERENCE"])
def test_template_exit_code_contrast(tmp_path, monkeypatch, missing):
    monkeypatch.setattr(sync, "collect_settings_env", lambda: {"SYNTHETIC_CONFIG_KEY": "fixture"})
    monkeypatch.setattr(sync, "collect_scanned_env", dict)
    for name in ("ENV_EXAMPLE", "CLOUD_ENV_EXAMPLE", "CONFIG_REFERENCE"):
        path = tmp_path / name
        content = "" if name == missing else "SYNTHETIC_CONFIG_KEY=example\n"
        path.write_text(content, encoding="utf-8")
        monkeypatch.setattr(sync, name, path)
    assert sync.main([]) == (0 if missing is None else 1)
