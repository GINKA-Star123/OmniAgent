from __future__ import annotations

from copy import deepcopy

import pytest

from aiagent.evaluation.scoring import evaluate_one
from aiagent.evaluation.semantic import minimum_judge_requests
from tests.unit.test_evaluation_contracts import semantic_case
from tests.unit.test_evaluation_derived_gold import decisions
from tests.unit.test_evaluation_judge_protocol import observation, provider, response, verdict
from tests.unit.test_evaluation_targeted_repairs import visual_fixture


@pytest.mark.parametrize(("kind", "inputs", "semantic", "split", "expected"), [
    ("vision_api", {}, True, True, 2),
    ("vision_api", {}, True, False, 1),
    ("api", {"steps": [{"image": "fixture.jpg"}]}, True, True, 2),
    ("api", {"steps": [{"image": "fixture.jpg"}]}, False, True, 0),
    ("api", {"steps": [{"image": "fixture.jpg"}]}, True, False, 1),
    ("persona", {}, True, True, 1),
    ("graph", {"image": "fixture.jpg"}, True, True, 2),
    ("rag", {}, True, True, 1),
    ("api", {"steps": [None, "invalid", {}]}, True, True, 1),
])
def test_minimum_counts_initial_channels_without_mutating_case(kind, inputs, semantic, split, expected):
    case = semantic_case().model_copy(update={"kind": kind, "inputs": inputs}, deep=True)
    case.oracle.semantic = semantic
    before = case.model_dump(mode="json")
    assert minimum_judge_requests(case, verify_visual_gold=split) == expected
    assert case.model_dump(mode="json") == before


@pytest.mark.parametrize(("budget", "used"), [(0, 0), (1, 0), (2, 1), (3, 2)])
@pytest.mark.parametrize("derive", [False, True])
def test_incomplete_visual_budget_never_generates_or_requests(tmp_path, monkeypatch, budget, used, derive):
    case, _, _, _ = visual_fixture(tmp_path, monkeypatch)
    judge, calls = provider(monkeypatch, [], verify_visual_gold=True, derive_gold_bindings=derive,
                            max_repairs=0, request_budget=budget)
    judge.usage["logical_requests"] = used

    def forbidden(*args):
        pytest.fail("SUT generation must not start without both initial channels")

    row = evaluate_one(case, tmp_path, "eval-fixture", judge, "budget@1", forbidden)
    assert row.status == "judge_error" and row.error_stage == "budget"
    assert row.error_code == "request_budget_exhausted" and row.metrics == {}
    assert row.observation_sha256 == "" and calls == []
    assert judge.usage["logical_requests"] == used


@pytest.mark.parametrize("derive", [False, True])
def test_exact_two_channel_budget_runs_once_and_keeps_low_quality(tmp_path, monkeypatch, derive):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    judge, calls = provider(monkeypatch, [response(visual), response(decisions(gold) if derive else gold)],
                            verify_visual_gold=True, derive_gold_bindings=derive, max_repairs=0, request_budget=2)
    generated = []
    row = evaluate_one(case, tmp_path, "eval-fixture", judge, "budget@1",
                       lambda *args: generated.append(True) or obs)
    assert row.status == "failed" and row.metrics["gold_coverage"] == 0
    assert generated == [True] and len(calls) == 2 and judge.usage["logical_requests"] == 2
    assert judge.identity["budget_policy"] == "complete-initial-review-v1"


def test_text_case_still_runs_with_one_request_and_optional_repairs_do_not_reserve_more(tmp_path, monkeypatch):
    judge, calls = provider(monkeypatch, [response(verdict())], max_repairs=1, request_budget=1,
                            verify_visual_gold=True)
    row = evaluate_one(semantic_case(), tmp_path, "eval-fixture", judge, "text@1", lambda *args: observation())
    assert row.status == "passed" and len(calls) == 1


@pytest.mark.parametrize(("visual_support", "persona_violation", "style_score"), [
    ("contradicted", True, 0.2), ("unclear", False, 0.7), ("visible", False, 0.95),
])
def test_compact_gold_placeholders_do_not_overwrite_visual_or_persona_judgments(
        tmp_path, monkeypatch, visual_support, persona_violation, style_score):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    visual["claims"][0]["visual_support"] = visual_support
    visual.update(persona_violation=persona_violation, style_score=style_score)
    before = deepcopy(visual)
    judge, _ = provider(monkeypatch, [response(visual), response(decisions(gold))], verify_visual_gold=True,
                        derive_gold_bindings=True, max_repairs=0, request_budget=2)
    row = evaluate_one(case, tmp_path, "eval-fixture", judge, "merge@1", lambda *args: obs)
    assert row.status == "failed" and row.metrics["gold_coverage"] == 0
    assert row.metrics["persona_consistency"] == int(not persona_violation)
    assert row.metrics["style_score"] == style_score
    assert row.metrics["visual_unsupported_rate"] == int(visual_support != "visible")
    assert visual == before
