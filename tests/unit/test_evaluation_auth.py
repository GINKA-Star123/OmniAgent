import asyncio
import json

import pytest

from aiagent.evaluation.http_support import evaluation_headers, run_steps
from config.settings import Settings


@pytest.fixture(autouse=True)
def clean_credentials(monkeypatch):
    for key in ("EVAL_API_TOKEN", "EVAL_API_PRINCIPAL", "EVAL_API_USER_TOKENS_FILE"):
        monkeypatch.delenv(key, raising=False)


def test_auth_settings_fail_closed_and_hide_verifiers():
    settings = Settings(_env_file=None, API_AUTH_TOKEN_SHA256_MAP='{"private-verifier":"eval-a"}')
    assert settings.api_auth_mode == "bearer"
    assert "api_auth_token_sha256_map" not in settings.model_dump()
    assert "private-verifier" not in repr(settings)


def test_single_token_must_match_exact_principal(monkeypatch):
    token = "a" * 43
    monkeypatch.setenv("EVAL_API_TOKEN", token)
    with pytest.raises(ValueError, match="principal mismatch"):
        evaluation_headers("eval-a")
    monkeypatch.setenv("EVAL_API_PRINCIPAL", "eval-a")
    assert evaluation_headers("eval-a") == {"Authorization": f"Bearer {token}"}
    with pytest.raises(ValueError, match="principal mismatch"):
        evaluation_headers("eval-b")


def test_registry_selects_only_requested_principal(monkeypatch, tmp_path):
    registry = tmp_path / "tokens.json"
    registry.write_text(json.dumps({"eval-a": "a" * 43, "eval-b": "b" * 43}))
    monkeypatch.setenv("EVAL_API_USER_TOKENS_FILE", str(registry))
    assert evaluation_headers("eval-a")["Authorization"] == "Bearer " + "a" * 43
    assert evaluation_headers("eval-b")["Authorization"] == "Bearer " + "b" * 43
    with pytest.raises(ValueError, match="credentials missing"):
        evaluation_headers("eval-c")


@pytest.mark.parametrize("contents", ['[]', '{"eval-a":"short"}', '{"eval-a":"x","eval-a":"y"}'])
def test_invalid_registry_never_echoes_content(monkeypatch, tmp_path, contents):
    registry = tmp_path / "tokens.json"
    registry.write_text(contents)
    monkeypatch.setenv("EVAL_API_USER_TOKENS_FILE", str(registry))
    with pytest.raises(ValueError) as raised:
        evaluation_headers("eval-a")
    assert contents not in str(raised.value)


def test_missing_credential_fails_before_network(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_BASE_URL", "http://isolated.test")
    monkeypatch.setenv("EVAL_ISOLATED", "1")
    monkeypatch.setenv("EVAL_API_USER_TOKENS_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(ValueError, match="registry invalid"):
        asyncio.run(run_steps([{"method": "GET", "path": "/memory/user/{user}/snapshot",
                               "checks": [{"pointer": "/ok", "value": True}]}], [], tmp_path, "eval-a"))
