from __future__ import annotations

import random
from collections import Counter, defaultdict

from aiagent.evaluation.contracts import Result
from aiagent.evaluation.metrics import macro_f1, mean, quantile, wilson

PROTOCOL = "agent-eval-four-layers-v2"


def summarize(rows: list[Result]) -> dict:
    groups = {"all": rows}
    for row in rows:
        groups.setdefault(f"{row.layer}.{row.domain}", []).append(row)
    output = {}
    for name, selected in groups.items():
        passed = sum(row.status == "passed" for row in selected)
        metric_names = sorted({key for row in selected for key in row.metrics})
        metrics = {
            key: {"mean": mean(row.metrics.get(key) for row in selected),
                  "applicable_n": sum(row.metrics.get(key) is not None for row in selected),
                  "total_n": len(selected)} for key in metric_names
        }
        pairs = [(row.gold_label, row.predicted_label or "__missing__")
                 for row in selected if row.gold_label is not None]
        labels = sorted({gold for gold, _ in pairs})
        by_label = {}
        for label in labels:
            tp = sum(g == label and p == label for g, p in pairs)
            fp = sum(g != label and p == label for g, p in pairs)
            fn = sum(g == label and p != label for g, p in pairs)
            by_label[label] = {"precision": tp / (tp + fp) if tp + fp else None,
                               "recall": tp / (tp + fn) if tp + fn else None,
                               "support": tp + fn}
        output[name] = {"total": len(selected), "passed": passed,
                        "pass_rate": passed / len(selected) if selected else None,
                        "pass_rate_ci95": wilson(passed, len(selected)),
                        "statuses": dict(Counter(row.status for row in selected)),
                        "scopes": dict(Counter(row.scope for row in selected)),
                        "metrics": metrics, "macro_f1": macro_f1(pairs, labels), "classification": by_label}
        identity_rows = [row for row in selected if row.identity_expected]
        if identity_rows:
            curve = []
            for threshold in (0.0, 0.5, 0.78, 0.9):
                accepted = [row for row in identity_rows if row.metrics.get("identity_accepted") == 1.0
                            and row.metrics.get("selection_score", 0) >= threshold]
                accuracy = mean(row.metrics.get("identity_exact_accuracy") for row in accepted)
                curve.append({"threshold": threshold, "coverage": len(accepted) / len(identity_rows),
                              "accuracy": accuracy, "risk": 1 - accuracy if accuracy is not None else None,
                              "total_n": len(identity_rows), "accepted_n": len(accepted)})
            output[name]["selective_identity"] = curve
    return output


def compare_reports(current: dict, baseline: dict, max_drop: float = 0.0) -> dict:
    if not 0 <= max_drop <= 1:
        raise ValueError("max_drop must be in [0, 1]")
    if current["protocol"] != baseline["protocol"] or current["conditions"] != baseline["conditions"]:
        raise ValueError("incompatible evaluation conditions")
    if current.get("overrides_sha256") != baseline.get("overrides_sha256"):
        raise ValueError("incompatible input overrides")
    if not baseline.get("ok"):
        raise ValueError("baseline must be a manually accepted passing report")
    now = {row["key"]: row for row in current["results"]}
    old = {row["key"]: row for row in baseline["results"]}
    if set(now) != set(old) or not now:
        raise ValueError("different or empty evaluation coverage")
    groups = defaultdict(list)
    regressions = []
    for key, row in now.items():
        previous = old[key]
        if any(row[field] != previous[field] for field in ("case_id", "group_id", "domain", "layer")):
            raise ValueError("changed case identity")
        if row["status"] != "error" and previous["scope"] != row["scope"]:
            raise ValueError("changed evidence scope")
        delta = float(row["status"] == "passed") - float(previous["status"] == "passed")
        groups[row["group_id"]].append(delta)
        if delta < 0:
            regressions.append(key)
    # Average repeats within group first; never treat turns/repeats as independent samples.
    values = [sum(items) / len(items) for items in groups.values()]
    rng = random.Random(20261022)
    samples = [sum(rng.choice(values) for _ in values) / len(values) for _ in range(2000)]
    delta = sum(values) / len(values)
    changes = {}
    for name, summary in current["summary"].items():
        prior = baseline["summary"].get(name)
        if prior is None or summary["total"] != prior["total"]:
            raise ValueError("changed summary coverage")
        changes[name] = summary["pass_rate"] - prior["pass_rate"]
    # Per-case limits remain enforced by current.ok; baseline tolerance cannot override them.
    return {"ok": all(change >= -max_drop for change in changes.values()),
            "group_mean_pass_delta": delta, "group_bootstrap_ci95": [quantile(samples, .025), quantile(samples, .975)],
            "groups": len(values), "unstable_ci": len(values) < 30,
            "pass_rate_delta": changes, "regressed_cases": regressions}
