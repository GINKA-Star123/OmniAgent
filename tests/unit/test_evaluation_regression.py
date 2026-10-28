import json

import pytest

from aiagent.evaluation import cli
from aiagent.evaluation.contracts import Dataset, Result, read_json
from aiagent.evaluation.reporting import compare_reports, summarize
from scripts.build_agent_eval_dataset import offline_dataset


def run_offline(tmp_path, monkeypatch, *extra):
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(offline_dataset(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cli, "code_identity", lambda: {"head": "test-only", "dirty": False})
    output = tmp_path / "reports"
    code = cli.main(["--dataset", str(path), "--output", str(output), *extra])
    report_path = next(output.glob("*/report.json"))
    return code, read_json(report_path), report_path


def test_offline_real_components_and_default_redaction(tmp_path, monkeypatch):
    code, report, _ = run_offline(tmp_path, monkeypatch)
    assert code == 0
    assert report["ok"]
    assert len(report["results"]) == len(offline_dataset()["cases"])
    assert report["summary"]["all"]["pass_rate"] == 1
    assert "offline_bm25" in report["summary"]["all"]["scopes"]
    for row in report["results"]:
        assert "answer" not in row and "data" not in row and "evidence" not in row
    assert "password=synthetic-evaluation-only" not in json.dumps(report)


def test_offline_is_not_release_acceptance(tmp_path, monkeypatch):
    code, report, _ = run_offline(tmp_path, monkeypatch, "--release")
    assert code == 1
    assert report["release_coverage_ok"] is False


def test_errors_stay_in_pass_rate_denominator():
    rows = [Result(key=f"c{i}@1", case_id=f"c{i}", group_id=f"g{i}", domain="memory", layer="task",
                   status=status) for i, status in enumerate(("passed", "failed", "error", "judge_error"))]
    summary = summarize(rows)["all"]
    assert summary["total"] == 4
    assert summary["pass_rate"] == .25


def test_baseline_comparison_and_incompatibility(tmp_path, monkeypatch):
    code, report, _ = run_offline(tmp_path, monkeypatch)
    assert code == 0
    assert compare_reports(report, report)["ok"]
    other = json.loads(json.dumps(report))
    other["conditions"]["repeat"] = 3
    with pytest.raises(ValueError):
        compare_reports(other, report)


def test_all_generated_dataset_inputs_validate():
    from aiagent.evaluation.adapters import validate_inputs
    from scripts.build_agent_eval_dataset import api_dataset, graph_dataset, provider_dataset

    for data in (offline_dataset(), provider_dataset(), api_dataset(), graph_dataset()):
        for case in Dataset.model_validate(data).cases:
            validate_inputs(case)
