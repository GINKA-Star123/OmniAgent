from copy import deepcopy

import pytest
from pydantic import ValidationError

from aiagent.evaluation.contracts import Case, Check, Dataset, Observation, Oracle, check_value, digest, read_json
from aiagent.evaluation.scoring import score
from aiagent.evaluation.semantic import Judge, Verdict
from scripts.build_agent_eval_dataset import offline_dataset


def semantic_case():
    return Case.model_validate({"case_id": "semantic", "group_id": "g", "domain": "rag",
        "layer": "component", "kind": "rag", "inputs": {"query": "q", "documents": {"a.txt": "资料"}},
        "oracle": {"semantic": True, "gold": {"color": "颜色是星蓝。"},
                   "limits": {"gold_coverage": {"minimum": 1}}}})


def test_dataset_rejects_duplicates_and_empty_oracle():
    raw = offline_dataset()
    raw["cases"].append(deepcopy(raw["cases"][0]))
    with pytest.raises(ValidationError):
        Dataset.model_validate(raw)
    with pytest.raises(ValidationError):
        Oracle()


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"a": 1, "a": 2}', encoding="utf-8")
    with pytest.raises(ValueError):
        read_json(path)


def test_pointer_distinguishes_absent_null_boolean_and_number():
    assert check_value({"a/b": [None]}, Check(pointer="/a~1b/0", value=None))
    assert not check_value({"x": True}, Check(pointer="/x", value=1))
    assert check_value({}, Check(pointer="/x", op="absent"))
    assert not check_value({"x": None}, Check(pointer="/x", op="absent"))
    assert check_value({"rows": [{"text": "用户喜欢星蓝"}]},
                       Check(pointer="/rows", op="text_contains", value="星蓝"))


def test_judge_rejects_fabricated_evidence_quotes():
    payload = {"answer": "星蓝", "evidence": {"doc": "星蓝"}, "gold": {"g": "星蓝"}}
    verdict = Verdict.model_validate({"claims": [{"quote": "星蓝", "support": "supported", "truth": "correct",
                "evidence_quotes": {"doc": "暗红"}}], "covered_gold_ids": ["g"],
                "persona_violation": False, "style_score": 1})
    with pytest.raises(ValueError):
        Judge.validate(verdict, payload)


def test_abstention_cannot_pass_gold_coverage():
    class AbstentionJudge:
        def evaluate(self, *args):
            return {"faithfulness": None, "gold_coverage": 0.0}

    result = score(semantic_case(), Observation(scope="provider_component", answer="不知道"),
                   AbstentionJudge(), "semantic@1")
    assert result.status == "failed"
    assert "metric_limit:gold_coverage" in result.failures


def test_judge_failure_is_not_a_pass():
    result = score(semantic_case(), Observation(scope="provider_component", answer="星蓝"), Judge(), "semantic@1")
    assert result.status == "judge_error"
    assert "judge_error" in result.failures


def test_manual_annotation_is_bound_to_exact_payload(tmp_path):
    import json

    case = semantic_case()
    obs = Observation(scope="provider_component", answer="星蓝", evidence={"doc": "星蓝"})
    payload = Judge().build_payload(case, obs)
    annotation = {"semantic@1": {"payload_sha256": digest(payload), "verdict": {
        "claims": [{"quote": "星蓝", "support": "supported", "truth": "correct",
                    "evidence_quotes": {"doc": "星蓝"}}], "covered_gold_ids": ["color"],
        "coverage_claims": {"color": ["星蓝"]},
        "persona_violation": False, "style_score": 1}}}
    path = tmp_path / "manual.json"
    path.write_text(json.dumps(annotation), encoding="utf-8")
    judge = Judge("manual", path)
    assert judge.evaluate("semantic@1", case, obs)["faithfulness"] == 1
    with pytest.raises(ValueError):
        judge.evaluate("semantic@1", case, obs.model_copy(update={"answer": "暗红"}))
