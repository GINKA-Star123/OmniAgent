import math

import pytest

from aiagent.evaluation.metrics import (
    macro_f1,
    ocr_scores,
    quantile,
    ranking,
    selection_curve,
    wilson,
)


def test_hit_is_not_recall_and_duplicate_source_does_not_inflate_score():
    result = ranking(["a", "a", "noise"], {"a": 3, "b": 1}, 2)
    assert result["hit@2"] == 1
    assert result["recall@2"] == .5
    assert result["precision@2"] == .5
    assert result["mrr@2"] == 1
    assert 0 < result["ndcg@2"] < 1


def test_short_return_uses_fixed_k_denominator():
    assert ranking(["a"], {"a": 1}, 5)["precision@5"] == .2


def test_unknown_query_has_no_fake_perfect_recall():
    scores = ranking([], {}, 3)
    assert scores["recall@3"] is None
    assert scores["ndcg@3"] is None


@pytest.mark.parametrize("bad", [0, -1, True])
def test_invalid_k_rejected(bad):
    with pytest.raises(ValueError):
        ranking([], {}, bad)


def test_quantile_and_nonfinite_rejection():
    assert quantile([0, 100], .95) == 95
    assert quantile([], .99) is None
    with pytest.raises(ValueError):
        quantile([math.nan], .95)


def test_ocr_handles_insertions_and_empty_reference():
    assert ocr_scores("甲", "甲乙丙")["cer"] == 2
    assert ocr_scores("", "甲")["cer"] is None
    assert ocr_scores("", "甲")["empty_ocr_accuracy"] == 0


def test_classification_and_wilson():
    assert macro_f1([("yes", "yes"), ("no", "no")]) == 1
    assert macro_f1([("yes", "no"), ("no", "yes")]) == 0
    assert wilson(0, 0) is None
    low, high = wilson(10, 10)
    assert 0 < low < high <= 1


def test_selection_must_report_coverage_not_only_accuracy():
    low, high = selection_curve([(.4, False), (.9, True)], [.3, .8])
    assert low["accuracy"] == .5 and low["coverage"] == 1
    assert high["accuracy"] == 1 and high["coverage"] == .5
    assert selection_curve([(.2, False)], [.8])[0]["accuracy"] is None