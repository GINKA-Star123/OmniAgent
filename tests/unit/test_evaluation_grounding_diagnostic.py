from __future__ import annotations

import json
from copy import deepcopy

import pytest

from aiagent.evaluation.semantic import JudgeError
from scripts import diagnose_judge_grounding as diagnostic
from scripts.build_adjudicated_regression import sha
from tests.unit.test_evaluation_judge_protocol import provider, response


@pytest.fixture
def rows(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "manifest.json").write_text("{}", encoding="utf-8")
    result = []
    for index, key in enumerate(diagnostic.CASE_IDS):
        path = candidate / f"fixture-{index // 2}.png"
        path.write_bytes(b"offline fixture " + str(index // 2).encode())
        result.append({"id": key, "images": [{"path": str(path), "sha256": sha(path)}],
            "payload": {"answer": "正确声明。" if index % 2 == 0 else "错误声明。"},
            "expected": {"visual_support": "visible" if index % 2 == 0 else "contradicted"}})
    return candidate, result


def scene():
    return {"objects": ["固定场景描述，不是人工真值。"], "relations": [], "uncertainty": ["无法确认细节。"]}


def replies():
    return [response(scene()), response(scene())] + [response({
        "relation": "entailed" if index % 2 == 0 else "contradicted",
        "evidence_quotes": ["固定场景描述"]}) for index in range(4)]


def test_blind_images_never_receive_claims_and_text_checks_never_receive_images(monkeypatch, tmp_path, rows):
    candidate, data = rows
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    judge, calls = provider(monkeypatch, replies(), max_repairs=0, request_budget=6)
    report = diagnostic.diagnose(data, judge, tmp_path, candidate)
    assert len(calls) == report["usage"]["logical_requests"] == 6
    assert report["summary"] == {"blind_scenes_valid": 2, "text_matches": 4, "text_mismatches": 0,
                                  "judge_errors": 0, "not_run": 0}
    assert report["quality_pass_rate"] is None
    assert report["semantic_judge_calibrated"] is report["baseline_eligible"] is False
    assert report["human_accepted"] is report["heldout_touched"] is report["sut_called"] is False
    for call in calls[:2]:
        assert call[0]["content"] == diagnostic.BLIND_PROMPT
        assert len(call[1]["content"]) == 2
        payload = json.loads(call[1]["content"][0]["text"])
        assert set(payload) == {"task", "image_sha256"}
        assert "正确声明" not in str(call) and "错误声明" not in str(call)
    for call in calls[2:]:
        assert call[0]["content"] == diagnostic.TEXT_PROMPT
        assert len(call[1]["content"]) == 1
        payload = json.loads(call[1]["content"][0]["text"])
        assert set(payload) == {"claim", "scene"}
        assert payload["scene"] == scene()
    assert "固定场景描述" not in (tmp_path / "report.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("reply,stage", [
    (response("not json"), "parse"),
    (response(scene(), finish_reason="length"), "response"),
    (JudgeError("request", "request_timeout"), "request"),
    (response(dict(scene(), objects=[""])), "validation"),
])
def test_error_stops_entire_diagnostic_without_retries(monkeypatch, tmp_path, rows, reply, stage):
    candidate, data = rows
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    judge, calls = provider(monkeypatch, [reply], max_repairs=0, request_budget=6)
    report = diagnostic.diagnose(data, judge, tmp_path, candidate)
    assert len(calls) == 1
    assert report["stopped_after_error"] is True
    assert report["summary"]["judge_errors"] == 1
    assert report["summary"]["not_run"] == 5
    assert report["results"][0]["error_stage"] == stage
    assert report["usage"]["repair_requests"] == 0


@pytest.mark.parametrize("reply", [
    {"relation": "entailed", "evidence_quotes": []},
    {"relation": "contradicted", "evidence_quotes": ["凭空编造的证据"]},
    {"relation": "contradicted", "evidence_quotes": ["无法确认细节"]},
    {"relation": "not_mentioned", "evidence_quotes": ["固定场景描述"]},
])
def test_text_check_requires_exact_non_uncertain_scene_evidence(monkeypatch, tmp_path, rows, reply):
    candidate, data = rows
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    judge, calls = provider(monkeypatch, [response(scene()), response(scene()), response(reply)],
                            max_repairs=0, request_budget=6)
    report = diagnostic.diagnose(data, judge, tmp_path, candidate)
    assert len(calls) == 3
    assert report["results"][2]["error_code"] == "scene_evidence_invalid"
    assert report["summary"]["not_run"] == 3


def test_semantic_mismatch_is_retained_and_does_not_trigger_retry(monkeypatch, tmp_path, rows):
    candidate, data = rows
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    answers = replies()
    answers[3] = response({"relation": "not_mentioned", "evidence_quotes": []})
    judge, calls = provider(monkeypatch, answers, max_repairs=0, request_budget=6)
    report = diagnostic.diagnose(data, judge, tmp_path, candidate)
    assert len(calls) == 6
    assert report["summary"]["text_mismatches"] == 1
    assert report["results"][3]["status"] == "mismatched"
    assert report["quality_pass_rate"] is None


@pytest.mark.parametrize("change", ["hash", "budget", "ids"])
def test_invalid_plan_is_rejected_before_provider_call(monkeypatch, tmp_path, rows, change):
    candidate, data = rows
    data = deepcopy(data)
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    budget = 6
    if change == "hash":
        data[0]["images"][0]["sha256"] = "0" * 64
    elif change == "budget":
        budget = 7
    else:
        data.reverse()
    judge, calls = provider(monkeypatch, [], max_repairs=0, request_budget=budget)
    with pytest.raises((ValueError, JudgeError)):
        diagnostic.diagnose(data, judge, tmp_path, candidate)
    assert not calls


@pytest.mark.parametrize("raw", [
    '{"objects":["a"],"objects":["b"],"relations":[],"uncertainty":[]}',
    '{"relation":"entailed","evidence_quotes":[],"score":NaN}',
])
def test_duplicate_keys_and_nonfinite_json_are_not_accepted(raw):
    with pytest.raises(JudgeError, match="diagnostic_schema_invalid"):
        diagnostic.parse(raw, diagnostic.BlindScene)


def test_cli_requires_execute_and_provider_consent_without_implicit_requests(monkeypatch, rows, capsys):
    _, data = rows
    monkeypatch.setattr(diagnostic, "selected_rows", lambda: data)

    def forbidden(*args, **kwargs):
        pytest.fail("dry-run和缺少许可时不得请求模型")

    monkeypatch.setattr(diagnostic.Judge, "_request", forbidden)
    assert diagnostic.main([]) == 0
    assert json.loads(capsys.readouterr().out)["network"] is False
    with pytest.raises(SystemExit):
        diagnostic.main(["--execute"])


def test_existing_plan_is_not_overwritten_or_replayed(monkeypatch, tmp_path, rows):
    candidate, data = rows
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    judge, calls = provider(monkeypatch, [], max_repairs=0, request_budget=6)
    (tmp_path / "plan.json").write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        diagnostic.diagnose(data, judge, tmp_path, candidate)
    assert not calls
    assert (tmp_path / "plan.json").read_text(encoding="utf-8") == "original"
