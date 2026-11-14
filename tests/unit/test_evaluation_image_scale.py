from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image

from scripts import calibrate_evaluation_image_scale as scaling
from scripts.build_adjudicated_regression import sha
from tests.unit.test_evaluation_judge_protocol import provider, response


@pytest.fixture
def rows(tmp_path):
    result = []
    for index, key in enumerate(scaling.CASE_IDS):
        path = tmp_path / f"small-{index // 2}.png"
        image = Image.new("RGB", (8, 6), "red" if index < 2 else "blue")
        image.putpixel((3, 2), (123, 45, 67))
        image.save(path)
        image_sha = sha(path)
        answer = "正确声明。" if index % 2 == 0 else "错误声明。"
        result.append({"id": key, "images": [{"path": str(path), "sha256": image_sha}],
            "payload": {"answer": answer, "fact_answers": [answer], "images_sha256": [image_sha],
                "claim_quotes": [answer], "gold": {}, "allowed_fact_ids": [], "allowed_behavior_ids": [],
                "evidence": {}}, "expected": {"visual_support": "visible" if index % 2 == 0 else "contradicted"}})
    return result


def test_nearest_neighbor_uses_only_source_pixels_and_does_not_mutate_inputs(tmp_path, rows):
    original = deepcopy(rows)
    scaled, manifest = scaling.prepare_scaled_rows(rows, tmp_path / "experiment/scaled-images")
    assert rows == original and len(scaled) == 8 and len(manifest["images"]) == 4
    assert manifest["original_resolution_pixels_used"] is manifest["generative_enhancement"] is False
    for row in scaled:
        base = original[scaling.CASE_IDS.index(row["id"].rsplit("-nn", 1)[0])]
        factor = int(row["id"].rsplit("-nn", 1)[1])
        image = row["images"][0]
        image_path = Path(image["path"])
        assert row["payload"]["images_sha256"] == [image["sha256"]] == [sha(image_path)]
        with Image.open(base["images"][0]["path"]) as source, Image.open(image_path) as resized:
            assert resized.size == (source.width * factor, source.height * factor)
            for y in range(source.height):
                for x in range(source.width):
                    assert resized.getpixel((x * factor, y * factor)) == source.getpixel((x, y))
                    assert resized.getpixel((x * factor + factor - 1, y * factor + factor - 1)) == source.getpixel((x, y))
        assert row["expected"] == base["expected"]
        assert row["payload"]["claim_quotes"] == base["payload"]["claim_quotes"]


@pytest.mark.parametrize("change", ["source_hash", "payload_hash", "ids"])
def test_invalid_source_is_rejected_before_generating_assets(tmp_path, rows, change):
    data = deepcopy(rows)
    if change == "source_hash":
        data[0]["images"][0]["sha256"] = "0" * 64
    elif change == "payload_hash":
        data[0]["payload"]["images_sha256"] = ["0" * 64]
    else:
        data.reverse()
    destination = tmp_path / "invalid/scaled-images"
    with pytest.raises(ValueError):
        scaling.prepare_scaled_rows(data, destination)
    assert not destination.exists()


def test_scaled_diagnostic_keeps_eight_requests_separate_and_labels_out_of_payload(monkeypatch, tmp_path, rows):
    scaled, manifest = scaling.prepare_scaled_rows(rows, tmp_path / "run/scaled-images")
    answers = [{"claims": [{"quote": row["payload"]["answer"], "truth": "unverifiable",
        "support": "insufficient", "evidence_quotes": {}, "citation_ids": [],
        "visual_support": row["expected"]["visual_support"]}], "covered_gold_ids": [],
        "coverage_claims": {}, "behavior_checks": {}, "persona_violation": False, "style_score": 1}
        for row in scaled]
    judge, calls = provider(monkeypatch, [response(answer) for answer in answers], max_repairs=0, request_budget=8)
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    report = scaling.calibrate(scaled, judge, tmp_path / "run", suite="visual",
                              identity={"transform": manifest["transform"]})
    assert len(calls) == report["usage"]["logical_requests"] == 8
    assert report["usage"]["repair_requests"] == 0
    for row, call in zip(scaled, calls, strict=True):
        payload = json.loads(call[1]["content"][0]["text"])
        assert payload["images_sha256"] == row["payload"]["images_sha256"]
        assert not {"expected", "source_image", "original_image", "visual_support"} & payload.keys()
    assert report["baseline_eligible"] is report["human_accepted"] is False
    assert report["sut_called"] is report["heldout_touched"] is False


def test_dry_run_and_missing_consent_never_request_provider(monkeypatch, rows, capsys):
    monkeypatch.setattr(scaling, "selected_rows", lambda: rows)
    def forbidden(*args, **kwargs):
        pytest.fail("未明确执行时不得调用模型")
    monkeypatch.setattr(scaling.Judge, "_request", forbidden)
    assert scaling.main([]) == 0
    assert json.loads(capsys.readouterr().out)["network"] is False
    with pytest.raises(SystemExit):
        scaling.main(["--execute"])
