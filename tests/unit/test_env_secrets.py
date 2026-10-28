from __future__ import annotations

import pytest

from config.env_secrets import resolve_named_secret


def test_named_secret_uses_dotenv_without_exporting_it(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EVAL_TEST_SECRET", raising=False)
    (tmp_path / ".env").write_text("EVAL_TEST_SECRET='fixture-secret'\n", encoding="utf-8")
    assert resolve_named_secret("EVAL_TEST_SECRET") == "fixture-secret"
    assert "EVAL_TEST_SECRET" not in __import__("os").environ


def test_process_environment_has_priority(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("EVAL_TEST_SECRET=dotenv-value\n", encoding="utf-8")
    monkeypatch.setenv("EVAL_TEST_SECRET", " process-value ")
    assert resolve_named_secret("EVAL_TEST_SECRET") == "process-value"


def test_explicit_empty_process_value_disables_fallback(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("EVAL_TEST_SECRET=dotenv-value\n", encoding="utf-8")
    monkeypatch.setenv("EVAL_TEST_SECRET", "")
    assert resolve_named_secret("EVAL_TEST_SECRET") is None


@pytest.mark.parametrize("reference", ["", "sk-not-a-variable", "../private", "KEY=value"])
def test_invalid_reference_is_not_read_as_a_variable(reference, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert resolve_named_secret(reference) is None


def test_absent_file_or_variable_returns_none(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EVAL_TEST_SECRET", raising=False)
    assert resolve_named_secret("EVAL_TEST_SECRET") is None
    (tmp_path / ".env").write_text("OTHER_VALUE=fixture\n", encoding="utf-8")
    assert resolve_named_secret("EVAL_TEST_SECRET") is None


def test_dotenv_secret_is_literal_and_supports_bom(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EVAL_TEST_SECRET", raising=False)
    monkeypatch.setenv("UNRELATED", "must-not-expand")
    (tmp_path / ".env").write_text("EVAL_TEST_SECRET='${UNRELATED}'\n", encoding="utf-8-sig")
    assert resolve_named_secret("EVAL_TEST_SECRET") == "${UNRELATED}"
