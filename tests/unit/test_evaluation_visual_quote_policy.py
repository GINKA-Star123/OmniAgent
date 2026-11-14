from __future__ import annotations

from copy import deepcopy

import pytest

from aiagent.evaluation.contracts import digest
from aiagent.evaluation.scoring import score
from aiagent.evaluation.semantic import JUDGE_PROMPT, VISUAL_REVIEW_PROMPT, Judge
from tests.unit.test_evaluation_judge_protocol import provider, response
from tests.unit.test_evaluation_targeted_repairs import visual_fixture


def test_visual_prompt_explicitly_prioritizes_original_spans():
    assert "连续原文约束优先于事实原子化" in VISUAL_REVIEW_PROMPT
    assert "没有桌子或椅子" in VISUAL_REVIEW_PROMPT
    assert "只有其中全部事实均被像素支持" in VISUAL_REVIEW_PROMPT
    assert "每个 claim 只含一项可独立核验的事实" not in VISUAL_REVIEW_PROMPT
    assert "连续原文约束优先于事实原子化" not in JUDGE_PROMPT
    judge = Judge(verify_visual_gold=False)
    assert judge.identity["visual_prompt_sha256"] == digest(VISUAL_REVIEW_PROMPT)
    assert judge.identity["visual_quote_rule"] == "combined-original"


@pytest.mark.parametrize(("answer", "quote"), [
    ("她穿白衣和蓝裙。", "她穿蓝裙"),
    ("没有桌子或椅子。", "没有椅子"),
    ("戴帽子，穿外套。", "人物戴帽子"),
    ("人物有蓝色、白色的配饰。", "人物有白色的配饰"),
])
def test_paraphrased_quotes_are_still_rejected_without_repair(tmp_path, monkeypatch, answer, quote):
    case, obs, visual, _ = visual_fixture(tmp_path, monkeypatch)
    obs.answer = answer
    visual["claims"][0]["quote"] = quote
    judge, calls = provider(monkeypatch, [response(visual)], verify_visual_gold=True, max_repairs=1)
    result = score(case, obs, judge, "quote@1")
    assert result.status == "judge_error" and result.error_code == "claim_quote_not_in_answer"
    assert len(calls) == 1 and judge.usage["repair_requests"] == 0
    assert result.metrics == {}
    assert calls[0][0]["content"] == VISUAL_REVIEW_PROMPT


@pytest.mark.parametrize("support", ["visible", "unclear", "contradicted"])
def test_compound_original_quote_keeps_actual_judgment_and_threshold(tmp_path, monkeypatch, support):
    case, obs, visual, gold = visual_fixture(tmp_path, monkeypatch)
    obs.answer = "没有桌子或椅子。"
    case.oracle.gold = {"object": obs.answer}
    for item in (visual, gold):
        item["claims"][0]["quote"] = obs.answer
    visual["claims"][0]["visual_support"] = support
    gold["claims"][0]["truth"] = "correct"
    gold.update(covered_gold_ids=["object"], coverage_claims={"object": [obs.answer]})
    gold["coverage_assessments"]["object"].update(gold_text=obs.answer, relation="entailed", claim_quotes=[obs.answer])
    original = deepcopy(visual)
    judge, calls = provider(monkeypatch, [response(visual), response(gold)],
                            verify_visual_gold=True, max_repairs=0, request_budget=2)
    result = score(case, obs, judge, "compound@1")
    assert result.status == ("passed" if support == "visible" else "failed")
    assert result.metrics["visual_unsupported_rate"] == (0 if support == "visible" else 1)
    assert result.metrics["gold_coverage"] == 1
    assert judge.identity["visual_quote_rule"] == "contiguous-before-atomic-v1"
    assert len(calls) == 2 and visual == original
