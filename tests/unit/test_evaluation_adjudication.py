from __future__ import annotations

import json
import socket
from copy import deepcopy

import pytest

from aiagent.evaluation.contracts import Case, Dataset, Observation, read_json
from aiagent.evaluation.semantic import Judge
from scripts.build_adjudicated_regression import (
    CALIBRATION,
    REVIEW,
    audit_debug,
    build,
    sha,
    snapshot,
    validate_calibration,
    write_new,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("审定与结构检查不允许访问网络")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture
def fixture_source(tmp_path):
    project = tmp_path / "project"
    source = project / "data/evaluation/frozen"
    source.mkdir(parents=True)
    original = project / "data/source.png"
    original.write_bytes(b"offline-image-fixture")
    source_hash = sha(original)
    group = "image-" + source_hash[:12]
    review = deepcopy(read_json(REVIEW))
    row = review["image_reviews"][0]
    review["image_reviews"] = [dict(row, source_sha256=source_hash, group_id=group)]
    review_path = project / "review.json"
    write_new(review_path, review)
    cases = []
    for suffix in ("normal", "small", "wrong-hint"):
        relative = "assets/" + suffix + ".jpg"
        path = source / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(("offline-" + suffix).encode())
        cases.append(Case(case_id="vision-" + source_hash[:12] + "-" + suffix,
            group_id=group, domain="vision", layer="component", split="regression", kind="vision_api",
            inputs={"steps": [{"path": "/vision/analyze", "method": "POST", "image": relative,
                "image_sha256": sha(path), "checks": [{"pointer": "/ok", "value": True}]}]},
            oracle={"semantic": True, "gold": {"old": "旧目标。"},
                "limits": {"gold_coverage": {"minimum": 1}, "visual_unsupported_rate": {"maximum": 0}}}))
    p = Case(case_id="persona-yzl-17", group_id="persona-17", domain="persona", layer="trajectory",
        kind="persona", inputs={"persona": {"identity": {"name": "fixture"}},
            "turns": ["朋友关系？", "怎么安慰？"]},
        oracle={"semantic": True, "gold": {"relationship": "天依是很好的朋友。", "care": "停止玩笑并安慰。"},
                "limits": {"gold_coverage": {"minimum": 1}, "persona_consistency": {"minimum": 1}}})
    for name, selected in (("api-vision-reviewed", cases), ("provider-persona", [p])):
        write_new(source / (name + ".json"), Dataset(version="agent-eval-system-v1",
            description="offline fixture", cases=selected).model_dump(mode="json"))
    write_new(source / "image-inventory.json", [{"source": "data/source.png", "source_sha256": source_hash,
        "group_id": group, "usable": True, "role": "query"}])
    write_new(source / "judge-gold-kinds.json", {p.case_id: {"care": "behavior"}})
    return project, source, source.with_name("candidate"), review_path


def run_build(fixture_source):
    project, source, output, review = fixture_source
    return build(source, output, review_path=review, source_root=project)


def test_build_preserves_frozen_inputs_thresholds_and_asset_bytes(fixture_source):
    _, source, output, _ = fixture_source
    before = snapshot(source)
    result = run_build(fixture_source)
    assert result["cases"] == 4 and result["image_groups"] == 1
    assert snapshot(source) == before
    manifest = read_json(output / "manifest.json")
    assert manifest["source_files_sha256"] == before and manifest["source_unchanged"]
    assert not any(manifest[key] for key in ("baseline_eligible", "human_accepted", "heldout_reviewed",
                                           "semantic_judge_calibrated", "providers_called"))
    for relative, expected in manifest["files_sha256"].items():
        assert sha(output / relative) == expected
    for relative, expected in manifest["assets"].items():
        assert sha(output / relative) == sha(source / relative) == expected
    old = Dataset.model_validate(read_json(source / "api-vision-reviewed.json"))
    new = Dataset.model_validate(read_json(output / "api-vision-adjudicated.json"))
    for a, b in zip(old.cases, new.cases, strict=True):
        assert (a.inputs, a.group_id, a.split, a.oracle.limits) == (b.inputs, b.group_id, b.split, b.oracle.limits)
        assert a.oracle.gold != b.oracle.gold
    p = read_json(output / "provider-persona-adjudicated.json")["cases"][0]
    assert p["inputs"]["fact_scope"] == "trajectory"
    assert p["oracle"]["gold"] == read_json(source / "provider-persona.json")["cases"][0]["oracle"]["gold"]
    assert read_json(output / "judge-gold-kinds.json")[p["case_id"]] == {"care": "behavior"}


@pytest.mark.parametrize("target", ["existing", "inside", "ancestor"])
def test_build_never_overwrites_source_or_existing_output(fixture_source, target):
    project, source, output, review = fixture_source
    if target == "existing":
        output.mkdir()
    elif target == "inside":
        output = source / "new"
    else:
        output = project
    before = snapshot(source)
    with pytest.raises(ValueError, match="不覆盖已有内容"):
        build(source, output, review_path=review, source_root=project)
    assert snapshot(source) == before


@pytest.mark.parametrize("mutation", ["heldout", "missing_variant", "bad_asset", "bad_original", "duplicate_group",
                                      "accepted", "bad_group", "blank_gold"])
def test_bad_review_or_source_fails_before_output(fixture_source, mutation):
    project, source, output, review_path = fixture_source
    review = read_json(review_path)
    path = source / "api-vision-reviewed.json"
    data = read_json(path)
    if mutation == "heldout":
        data["cases"][0]["split"] = "heldout"
    elif mutation == "missing_variant":
        data["cases"].pop()
    elif mutation == "bad_asset":
        (source / data["cases"][0]["inputs"]["steps"][0]["image"]).write_bytes(b"changed")
    elif mutation == "bad_original":
        (project / "data/source.png").write_bytes(b"changed")
    elif mutation == "duplicate_group":
        review["image_reviews"] *= 2
    elif mutation == "accepted":
        review["baseline_eligible"] = True
    elif mutation == "bad_group":
        review["image_reviews"][0]["group_id"] = "unknown"
    else:
        review["image_reviews"][0]["gold"] = {"blank": " "}
    path.write_text(json.dumps(data), encoding="utf-8")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    before = snapshot(source)
    with pytest.raises(ValueError):
        run_build(fixture_source)
    assert not output.exists() and snapshot(source) == before


def test_persona_trajectory_uses_actual_assistant_answers_not_config_or_questions(fixture_source):
    run_build(fixture_source)
    _, _, output, _ = fixture_source
    case = Dataset.model_validate(read_json(output / "provider-persona-adjudicated.json")).cases[0]
    obs = Observation(scope="offline-fixture", answer="我会停下玩笑，认真道歉并安慰。", data={"history": [
        {"user": "朋友关系？", "answer": "天依是我特别好的朋友。"},
        {"user": "怎么安慰？", "answer": "我会停下玩笑，认真道歉并安慰。"}]})
    payload = Judge().build_payload(case, obs)
    assert payload["fact_scope"] == "trajectory"
    assert "天依是我特别好的朋友。" in payload["fact_answers"]
    assert "朋友关系？" not in payload["fact_answers"]
    assert len(payload["fact_answers"]) == 2


def test_calibration_reference_is_not_a_model_execution():
    value = read_json(CALIBRATION)
    validate_calibration(value)
    assert len(value["cases"]) == 24
    by_id = {row["id"]: row for row in value["cases"]}
    assert by_id["fruit-specific"]["relation"] == "entailed"
    assert by_id["fruit-specific"]["truth"] == "unverifiable"
    assert by_id["fruit-too-general"]["relation"] == "partial"
    assert by_id["fruit-too-general"]["truth"] == "correct"
    assert by_id["partial-not-majority"]["relation"] != "entailed"
    assert by_id["planter-not-flowers"]["relation"] != "entailed"


@pytest.mark.parametrize("change", ["duplicate", "relation", "truth", "valid_quote", "invalid_quote"])
def test_calibration_schema_rejects_invalid_references(change):
    value = deepcopy(read_json(CALIBRATION))
    if change == "duplicate":
        value["cases"].append(value["cases"][0])
    elif change in {"relation", "truth"}:
        value["cases"][0][change] = "unknown"
    else:
        value["cases"][0][change] = "并非原文" if change == "valid_quote" else value["cases"][0]["answer"]
    with pytest.raises(ValueError):
        validate_calibration(value)


def test_historical_audit_flags_semantic_upgrade_and_fabricated_quote_without_regrading(tmp_path):
    answer = "画面中没有海边、钢琴或弹琴动作。"
    for attempt, relation in ((1, "partial"), (2, "entailed")):
        raw = {"claims": [{"quote": "没有钢琴"}],
               "coverage_assessments": {"clothing": {"relation": relation}}}
        write_new(tmp_path / ("a" * 24 + f"-{attempt}.json"),
                  {"payload": {"answer": answer}, "raw_verdict": json.dumps(raw)})
    before = snapshot(tmp_path)
    audit = audit_debug(tmp_path)
    assert len(audit["invalid_quote_artifacts"]) == 2
    assert audit["coverage_relation_changes"][0]["upgraded_to_entailed"] is True
    assert not audit["historical_scores_rewritten"] and snapshot(tmp_path) == before
    assert answer not in json.dumps(audit, ensure_ascii=False)


def test_path_escape_is_rejected(fixture_source):
    _, source, output, _ = fixture_source
    path = source / "api-vision-reviewed.json"
    data = read_json(path)
    data["cases"][0]["inputs"]["steps"][0]["image"] = "../../source.png"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="越界"):
        run_build(fixture_source)
    assert not output.exists()
