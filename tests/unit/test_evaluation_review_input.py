from __future__ import annotations

import os
import stat

import pytest

from aiagent.evaluation.contracts import digest, read_json
from aiagent.evaluation.diagnostics import LocalJudgeDebug
from aiagent.evaluation.scoring import score
from tests.unit.test_evaluation_contracts import semantic_case
from tests.unit.test_evaluation_judge_protocol import observation, provider, response, verdict


def local(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("CLOUD_MODE", "false")


@pytest.mark.parametrize("reply", [RuntimeError("private request failure"), response("bad JSON"),
                                   response(verdict(), "length"), response(verdict())])
def test_input_survives_request_parse_truncation_and_success(tmp_path, monkeypatch, reply):
    local(monkeypatch)
    directory = tmp_path / ".judge-debug"
    judge, calls = provider(monkeypatch, [reply], max_repairs=0, debug_directory=directory)
    key = "fixture@1"
    expected = judge.build_payload(semantic_case(), observation())
    result = score(semantic_case(), observation(), judge, key)
    stored = read_json(directory / f"{digest(key)[:24]}-input.json")
    assert len(calls) == 1
    assert stored["payload"] == expected
    assert stored["payload_sha256"] == stored["stored_payload_sha256"] == digest(expected)
    assert stored["payload_transformed"] is False
    assert stored["human_accepted"] is stored["baseline_eligible"] is False
    assert stored["automatic_replay_allowed"] is False
    assert "private request failure" not in str(stored)
    assert observation().answer not in result.model_dump_json()


def test_snapshot_is_written_before_any_paid_request(tmp_path, monkeypatch):
    local(monkeypatch)
    directory = tmp_path / ".judge-debug"
    judge, _ = provider(monkeypatch, [], max_repairs=0, debug_directory=directory)

    def request(messages):
        files = list(directory.glob("*-input.json"))
        assert len(files) == 1
        assert read_json(files[0])["payload"]["answer"] == observation().answer
        return response(verdict())

    monkeypatch.setattr(judge, "_request", request)
    assert score(semantic_case(), observation(), judge, "before@1").status == "passed"


def test_snapshot_write_failure_stops_before_request(tmp_path, monkeypatch):
    local(monkeypatch)
    judge, calls = provider(monkeypatch, [response(verdict())], debug_directory=tmp_path / ".debug")

    def fail(*args):
        raise OSError("sensitive local path")

    monkeypatch.setattr(judge.debug, "write_input", fail)
    result = score(semantic_case(), observation(), judge, "failure@1")
    assert result.status == "judge_error" and result.error_code == "debug_artifact_write_failed"
    assert calls == [] and judge.usage["logical_requests"] == 0
    assert "sensitive local path" not in result.model_dump_json()


def test_snapshot_redacts_secrets_and_marks_modified_payload(tmp_path, monkeypatch):
    local(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "private-fixture-key")
    debug = LocalJudgeDebug(tmp_path / ".debug")
    original = {"answer": "private-fixture-key", "history": [], "images_sha256": ["0" * 64]}
    debug.write_input("../not-a-path", original)
    files = list(debug.directory.glob("*-input.json"))
    assert len(files) == 1 and files[0].parent == debug.directory
    stored = read_json(files[0])
    assert "private-fixture-key" not in files[0].read_text()
    assert original["answer"] == "private-fixture-key"
    assert stored["payload_sha256"] == digest(original)
    assert stored["stored_payload_sha256"] == digest(stored["payload"])
    assert stored["payload_transformed"] is True
    assert stored["automatic_replay_allowed"] is False
    if os.name == "posix":
        assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
        assert stat.S_IMODE(debug.directory.stat().st_mode) == 0o700


def test_snapshot_size_limits_do_not_claim_original_content(tmp_path, monkeypatch):
    local(monkeypatch)
    debug = LocalJudgeDebug(tmp_path / ".debug")
    payload = {"answer": "a" * 40000}
    debug.write_input("long@1", payload)
    stored = read_json(next(debug.directory.glob("*-input.json")))
    assert stored["payload_transformed"] is True
    assert len(stored["payload"]["answer"]) < len(payload["answer"])
    assert stored["payload_sha256"] != stored["stored_payload_sha256"]


def test_snapshot_and_verdict_cannot_overwrite_each_other(tmp_path, monkeypatch):
    local(monkeypatch)
    debug = LocalJudgeDebug(tmp_path / ".debug")
    debug.write_input("fixture@1", {"answer": "plain fixture"})
    debug.write("fixture@1", 1, {"answer": "plain fixture"}, "{}")
    assert len(list(debug.directory.glob("*.json"))) == 2
    before = {path.name: path.read_bytes() for path in debug.directory.glob("*.json")}
    with pytest.raises(FileExistsError):
        debug.write_input("fixture@1", {"answer": "replacement"})
    assert before == {path.name: path.read_bytes() for path in debug.directory.glob("*.json")}


def test_no_snapshot_when_debug_is_disabled(tmp_path, monkeypatch):
    judge, calls = provider(monkeypatch, [response(verdict())], max_repairs=0)
    assert judge.debug is None
    assert score(semantic_case(), observation(), judge, "disabled@1").status == "passed"
    assert len(calls) == 1 and list(tmp_path.iterdir()) == []
