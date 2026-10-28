from __future__ import annotations

import json
from copy import deepcopy

import pytest

from aiagent.evaluation.contracts import Dataset, Observation, digest
from aiagent.evaluation.reporting import compare_reports
from aiagent.evaluation.scoring import score
from aiagent.evaluation.semantic import Judge, Verdict
from aiagent.evaluation.source_attribution import gold_document_titles, is_gold_source_label
from scripts.regrade_judge_sources import main, regrade_report
from tests.unit.test_evaluation_judge_protocol import provider, response
from tests.unit.test_evaluation_rag_generation import birthday_case


def source_case():
    case = birthday_case()
    case.oracle.gold = {"fact": "《星桥》“基本资料”记载：生日：9月6日。"}
    return case


def raw_verdict(date="9月6日", label="（来源：《星桥.md》）", date_truth="correct", source_truth="unverifiable"):
    return {"claims": [{"quote": date, "support": "insufficient", "truth": date_truth},
                       {"quote": label, "support": "insufficient", "truth": source_truth}],
            "covered_gold_ids": ["fact"] if date_truth == "correct" else [],
            "coverage_claims": {"fact": [date]} if date_truth == "correct" else {},
            "behavior_checks": {}, "persona_violation": False, "style_score": 1}


@pytest.mark.parametrize("label", ["来源：《星桥.md》", "（来源：《星桥.md》）", "(来源：《星桥》)"])
def test_explicit_source_alias_is_correct_without_changing_raw_or_evidence(monkeypatch, label):
    raw = raw_verdict(label=label)
    judge, calls = provider(monkeypatch, [response(raw)])
    result = score(source_case(), Observation(scope="fixture", answer="9月6日。" + label), judge, "b@1")
    assert result.status == "passed" and len(calls) == 1
    metrics = result.metrics
    assert metrics["fact_accuracy"] == 1 and metrics["fact_accuracy_raw"] == .5
    assert metrics["fact_unverifiable_rate"] == 0 and metrics["fact_unverifiable_rate_raw"] == .5
    assert metrics["claim_count"] == 2 and metrics["source_alias_correction_count"] == 1
    assert metrics["faithfulness"] is None and metrics["citation_accuracy"] is None
    assert metrics["citation_coverage"] == 0
    payload = json.loads(calls[0][1]["content"][0]["text"])
    assert payload["gold_document_titles"] == ["星桥"] and payload["evidence"] == {}


@pytest.mark.parametrize("label", ["来源：《其他.md》", "来源：《星桥.txt》", "来源：《星桥.MD》",
    "来源：《path/星桥.md》", "来源：《星桥.md》，发布于2014年", "来源：《星桥.md》2014年版",
    "来源：《星桥.md》）", "来源：《 星桥.md》", "来源：《星桥.md》\n还有2014年",
    "《星桥.md》", "（来源：《星桥.md》)违反约束"])
def test_wrong_unknown_or_extended_sources_are_not_calibrated(monkeypatch, label):
    raw = raw_verdict(label=label)
    judge, calls = provider(monkeypatch, [response(raw)])
    result = score(source_case(), Observation(scope="fixture", answer="9月6日。" + label), judge, "b@1")
    assert result.status == "failed" and len(calls) == 1
    assert result.metrics["fact_accuracy"] == .5
    assert result.metrics["source_alias_correction_count"] == 0


def test_correct_source_does_not_hide_incorrect_date(monkeypatch):
    raw = raw_verdict(date="9月7日", date_truth="incorrect")
    judge, calls = provider(monkeypatch, [response(raw)])
    result = score(source_case(), Observation(scope="fixture", answer="9月7日。（来源：《星桥.md》）"), judge, "b@1")
    assert result.status == "failed" and len(calls) == 1
    assert result.metrics["fact_accuracy"] == .5 and result.metrics["fact_contradiction_rate"] == .5
    assert result.metrics["fact_contradiction_rate_raw"] == .5


def test_extra_year_is_not_removed_from_denominator():
    case = source_case()
    payload = Judge().build_payload(case, Observation(scope="fixture", answer="9月6日。（来源：《星桥.md》）。2014年发布。"))
    raw = raw_verdict()
    raw["claims"].append({"quote": "2014年发布", "support": "insufficient", "truth": "unverifiable"})
    verdict = Verdict.model_validate(raw)
    before = verdict.model_dump()
    result = Judge.score_verdict(verdict, payload)
    assert result["fact_accuracy"] == 2 / 3 and result["fact_accuracy_raw"] == 1 / 3
    assert result["claim_count"] == 3 and result["fact_unverifiable_rate"] == 1 / 3
    assert verdict.model_dump() == before


@pytest.mark.parametrize("gold", ["星桥演唱了《星桥》。", "据《星桥》记载：生日9月6日。",
    "《星桥》是作品名，生日9月6日。", "《path/星桥》记载：9月6日。", "《..》记载：9月6日。"])
def test_mentions_or_paths_are_not_explicit_gold_provenance(gold):
    assert gold_document_titles({"g": gold}, ["g"]) == []


def test_behavior_gold_cannot_supply_source_aliases():
    case = source_case()
    judge = Judge(gold_kinds={case.case_id: {"fact": "behavior"}})
    payload = judge.build_payload(case, Observation(scope="fixture"))
    assert payload["gold_document_titles"] == []
    assert not is_gold_source_label("来源：《星桥.md》", [], "来源：《星桥.md》")


@pytest.mark.parametrize("answer", ["9月6日。这不是来源：《星桥.md》。", "9月6日。（来源：《星桥.md》）2014年版。"])
def test_partial_source_quote_inside_longer_assertion_is_not_calibrated(answer):
    payload = Judge().build_payload(source_case(), Observation(scope="fixture", answer=answer))
    verdict = Verdict.model_validate(raw_verdict(label="来源：《星桥.md》"))
    metrics = Judge.score_verdict(verdict, payload)
    assert metrics["fact_accuracy"] == .5 and metrics["source_alias_correction_count"] == 0


def test_explicit_incorrect_judgment_is_not_overridden():
    case = source_case()
    payload = Judge().build_payload(case, Observation(scope="fixture", answer="9月6日。（来源：《星桥.md》）"))
    metrics = Judge.score_verdict(Verdict.model_validate(raw_verdict(source_truth="incorrect")), payload)
    assert metrics["fact_accuracy"] == .5 and metrics["source_alias_correction_count"] == 0


def test_source_calibration_does_not_bypass_evidence_validation():
    case = source_case()
    payload = Judge().build_payload(case, Observation(scope="fixture", answer="9月6日。（来源：《星桥.md》）"))
    raw = raw_verdict()
    raw["claims"][1]["support"] = "supported"
    with pytest.raises(ValueError, match="supported_evidence_missing"):
        Judge.score_verdict(Verdict.model_validate(raw), payload)


def test_matching_gold_source_does_not_create_injected_support():
    case = source_case()
    payload = Judge().build_payload(case, Observation(scope="fixture", answer="9月6日。（来源：《星桥.md》）",
                                                     evidence={"chunk": "生日：9月6日"}))
    raw = raw_verdict()
    raw["claims"][0].update(support="supported", evidence_quotes={"chunk": "生日：9月6日"})
    verdict = Verdict.model_validate(raw)
    metrics = Judge.score_verdict(verdict, payload)
    assert metrics["fact_accuracy"] == 1 and metrics["faithfulness"] == .5
    assert verdict.claims[1].support == "insufficient" and verdict.claims[1].evidence_quotes == {}


def test_new_judge_protocol_cannot_compare_against_v2():
    current = {"protocol": "evaluation", "conditions": {"judge": Judge().identity}}
    old = deepcopy(current)
    old["conditions"]["judge"]["protocol"] = "judge-v2"
    with pytest.raises(ValueError, match="incompatible"):
        compare_reports(current, old)


def archive(tmp_path):
    case = source_case()
    dataset = Dataset(version="agent-eval-system-v1", description="archive", cases=[case])
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(dataset.model_dump_json(), encoding="utf-8")
    payload = Judge().build_payload(case, Observation(scope="fixture", answer="9月6日。（来源：《星桥.md》）"))
    for field in ("gold_document_titles", "fact_scope", "fact_answers", "last_answer"):
        payload.pop(field)
    raw = raw_verdict()
    raw.pop("coverage_claims")
    metrics = Judge.score_verdict(Verdict.model_validate(raw), payload, legacy_coverage=True)
    for name in ("fact_accuracy", "fact_contradiction_rate", "fact_unverifiable_rate"):
        metrics[name] = metrics.pop(name + "_raw")
    metrics.pop("source_alias_correction_count")
    metrics.pop("claim_count")
    key = case.case_id + "@1"
    debug_dir = tmp_path / ".judge-debug"
    debug_dir.mkdir()
    debug_path = debug_dir / f"{digest(key)[:24]}-1.json"
    debug = {"payload_sha256": digest(payload), "payload": payload, "raw_verdict": json.dumps(raw, ensure_ascii=False)}
    debug_path.write_text(json.dumps(debug, ensure_ascii=False), encoding="utf-8")
    report = {"conditions": {"judge": {"protocol": "judge-v2", "gold_kinds_sha256": digest({})},
                              "dataset_sha256": digest(dataset.model_dump(mode="json"))},
              "overrides_sha256": digest({}), "results": [{"case_id": case.case_id, "key": key,
              "status": "failed", "error_type": "", "metrics": metrics,
              "failures": ["metric_limit:fact_accuracy"],
              "judge_diagnostics": [{"attempt": 1, "stage": "complete", "code": "ok"}]}]}
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path, dataset_path, debug_path


def test_replay_is_offline_separate_and_does_not_modify_history(tmp_path, monkeypatch):
    report_path, dataset_path, debug_path = archive(tmp_path)
    before = {path: path.read_bytes() for path in (report_path, dataset_path, debug_path)}
    monkeypatch.setattr(Judge, "_request", lambda *args: pytest.fail("replay must never request a model"))
    output = tmp_path / "replay"
    args = ["--report", str(report_path), "--dataset", str(dataset_path), "--output", str(output)]
    assert main(args) == 0
    result = json.loads((output / "regrade.json").read_text(encoding="utf-8"))
    assert result["kind"] == "retrospective_semantic_regrade"
    assert result["semantic_limits_passed"] == 1 and result["new_provider_requests"] == 0
    assert "ok" not in result and "conditions" not in result
    assert result["cases"][0]["original_status"] == "failed"
    assert result["scorer_identity"]["protocol"] == "legacy-v2-source-only"
    assert result["scorer_identity"]["coverage_bindings_validated"] is False
    assert all(path.read_bytes() == content for path, content in before.items())
    assert main(args) == 2  # Never overwrite even a replay archive.


@pytest.mark.parametrize("mutation", ["dataset", "payload", "gold", "raw", "metrics", "images", "overrides"])
def test_replay_rejects_unbound_or_incomplete_artifacts(tmp_path, mutation):
    report_path, dataset_path, debug_path = archive(tmp_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    debug = json.loads(debug_path.read_text(encoding="utf-8"))
    if mutation == "dataset":
        report["conditions"]["dataset_sha256"] = "changed"
    elif mutation == "payload":
        debug["payload"]["answer"] = "changed"
    elif mutation == "gold":
        debug["payload"]["gold"]["fact"] = "changed"
        debug["payload_sha256"] = digest(debug["payload"])
    elif mutation == "raw":
        debug["raw_verdict"] = json.dumps(raw_verdict(date="9月7日"))
    elif mutation == "metrics":
        report["results"][0]["metrics"]["fact_accuracy"] = 1
    elif mutation == "images":
        debug["payload"]["images_sha256"] = ["unavailable"]
        debug["payload_sha256"] = digest(debug["payload"])
    else:
        report["overrides_sha256"] = digest({"changed": True})
    report_path.write_text(json.dumps(report), encoding="utf-8")
    debug_path.write_text(json.dumps(debug), encoding="utf-8")
    with pytest.raises(ValueError):
        regrade_report(report_path, dataset_path)
