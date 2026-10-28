from __future__ import annotations

import math
from collections.abc import Iterable


def mean(values: Iterable[float | None]) -> float | None:
    usable = [x for x in values if x is not None]
    return sum(usable) / len(usable) if usable else None

def quantile(values: list[float], q: float) -> float | None:
    if not 0 <= q <= 1 or any(not math.isfinite(x) for x in values):
        raise ValueError("invalid quantile input")
    if not values:
        return None
    ordered = sorted(values)
    at = (len(ordered) - 1) * q
    low, high = math.floor(at), math.ceil(at)
    return ordered[low] + (ordered[high] - ordered[low]) * (at - low)

def ranking(retrieved: list[str], grades: dict[str, int], k: int) -> dict[str, float | None]:
    if type(k) is not int or k<1:
        raise ValueError("k must be positive")
    ids = list(dict.fromkeys(retrieved))[:k]
    relevant = {key for key, grade in grades.items() if grade > 0}
    hits = [int(key in relevant) for key in ids]
    hit_count = sum(hits)
    dcg = sum((2 ** grades.get(key, 0) - 1) / math.log2(i + 2) for i, key in enumerate(ids))
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum((2 ** grade - 1) / math.log2(i + 2) for i, grade in enumerate(ideal))
    first = next((i + 1 for i, hit in enumerate(hits) if hit), None)
    return {
        f"hit@{k}": float(hit_count > 0) if relevant else None,
        f"recall@{k}": hit_count / len(relevant) if relevant else None,
        f"precision@{k}": hit_count / k,
        f"mrr@{k}": (1 / first if first else 0.0) if relevant else None,
        f"ndcg@{k}": dcg / idcg if idcg else None,
    }

def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, 1):
        current = [i]
        for j, hyp in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (ref != hyp)))
        previous = current
    return previous[-1]

def ocr_scores(reference: str, hypothesis: str) -> dict[str, float | None]:
    words = reference.split()
    return {
        "cer": edit_distance(list(reference), list(hypothesis)) / len(reference) if reference else None,
        "wer": edit_distance(words, hypothesis.split()) / len(words) if words else None,
        "empty_ocr_accuracy": float(not hypothesis) if not reference else None,
    }

def macro_f1(pairs: list[tuple[str, str]], labels: list[str] | None = None) -> float | None:
    classes = labels or sorted({item for pair in pairs for item in pair})
    if not pairs or not classes:
        return None
    scores = []
    for label in classes:
        tp = sum(g == label and p == label for g, p in pairs)
        fp = sum(g != label and p == label for g, p in pairs)
        fn = sum(g == label and p != label for g, p in pairs)
        denominator = 2 * tp + fp + fn
        scores.append(2 * tp / denominator if denominator else 0.0)
    return sum(scores) / len(scores)

def wilson(passed: int, total: int) -> list[float] | None:
    if total < 0 or not 0<= passed <= total:
        raise ValueError("invalid counts")
    if not total:
        return None
    z = 1.959963984540054
    p = passed / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]

def selection_curve(rows: list[tuple[float, bool]], thresholds: list[float]) -> list[dict]:
    if any(not 0 <= score <= 1 for score, _ in rows):
        raise ValueError("selection scores must be in [0, 1]")
    if any(not 0 <= threshold <= 1 for threshold in thresholds):
        raise ValueError("invalid threshold")
    result = []
    for threshold in thresholds:
        selected = [correct for score, correct in rows if score >= threshold]
        accuracy = sum(selected) / len(selected) if selected else None
        result.append({"threshold": threshold, "coverage": len(selected) / len(rows) if rows else None,
                       "accuracy": accuracy, "risk": 1 - accuracy if accuracy is not None else None})
    return result
