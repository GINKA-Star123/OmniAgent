from __future__ import annotations

import time

from aiagent.evaluation.contracts import Case, Observation, Result, check_value, digest
from aiagent.evaluation.http_support import EvaluationHTTPError
from aiagent.evaluation.metrics import ocr_scores, ranking
from aiagent.evaluation.semantic import Judge, JudgeError
from aiagent.knowledge.evaluation.answer import evaluate_answer


def score(case: Case, observation: Observation, judge: Judge, key: str) -> Result:
    metrics, failures = {}, []
    metadata = observation.data.get("metadata", {})
    last = observation.data.get("last")
    if isinstance(last, dict) and isinstance(last.get("body"), dict):
        metadata = last["body"].get("metadata", {})
    if isinstance(metadata, dict) and metadata.get("llm_answer_mode") in ("extractive_rag_fact", "model"):
        metrics["extractive_answer_used"] = float(metadata["llm_answer_mode"] == "extractive_rag_fact")
    value = observation.model_dump(mode="json")
    for index, check in enumerate(case.oracle.checks):
        if not check_value(value, check):
            failures.append(f"check:{index}")
    if case.oracle.required_terms or case.oracle.forbidden_terms:
        rule = evaluate_answer(observation.answer, required_terms=case.oracle.required_terms,
                               forbidden_terms=case.oracle.forbidden_terms)
        metrics["answer_rule_pass_rate"] = float(rule.passed)
        if not rule.passed:
            failures.append("answer_rules")
    if case.oracle.relevance:
        for k in case.oracle.ks:
            metrics.update(ranking(observation.retrieved, case.oracle.relevance, k))
    if case.oracle.label is not None:
        metrics["label_accuracy"] = float(case.oracle.label == observation.label)
        if not metrics["label_accuracy"]:
            failures.append("label_mismatch")
    if case.oracle.ocr is not None:
        if observation.ocr is None:
            failures.append("ocr_missing")
        else:
            metrics.update(ocr_scores(case.oracle.ocr, observation.ocr))
    if case.oracle.identity_ids is not None:
        actual = observation.data.get("confirmed_ids")
        if actual is None:
            actual = [item["character_id"] for item in observation.data.get("recognized_characters", [])]
        expected = set(case.oracle.identity_ids)
        metrics["identity_exact_accuracy"] = float(set(actual) == expected)
        metrics["identity_accepted"] = float(bool(actual))
        metrics["identity_accepted_correct"] = float(bool(actual) and set(actual) == expected)
        metrics["unknown_false_confirmation"] = float(bool(actual)) if not expected else None
        metrics["selection_score"] = float(observation.data.get("score", observation.data.get("confidence", 0)))
        if set(actual) != expected:
            failures.append("identity_mismatch")
    events = observation.events
    for event in case.oracle.required_events:
        if event not in events:
            failures.append(f"event_required:{event}")
    for event in case.oracle.forbidden_events:
        if event in events:
            failures.append(f"event_forbidden:{event}")
    for before, after in case.oracle.before:
        if before not in events or after not in events or events.index(before) >= events.index(after):
            failures.append(f"event_order:{before}:{after}")
    if case.oracle.required_events or case.oracle.forbidden_events or case.oracle.before:
        metrics["trajectory_constraint_pass_rate"] = float(not any(f.startswith("event_") for f in failures))
    error_type, error_code, error_stage = "", "", ""
    if case.oracle.semantic:
        try:
            metrics.update(judge.evaluate(key, case, observation))
        except Exception as exc:
            error_type = type(exc).__name__
            if isinstance(exc, JudgeError):
                error_code, error_stage = exc.code, exc.stage
            else:
                error_code, error_stage = "judge_internal_error", "internal"
            failures.append("judge_error")
    for name, limit in case.oracle.limits.items():
        number = metrics.get(name)
        if number is None:
            failures.append(f"metric_missing:{name}")
        elif ((limit.minimum is not None and number < limit.minimum)
              or (limit.maximum is not None and number > limit.maximum)):
            failures.append(f"metric_limit:{name}")
    return Result(key=key, case_id=case.case_id, group_id=case.group_id,
                  domain=case.domain, layer=case.layer,
                  status="judge_error" if error_type else ("failed" if failures else "passed"),
                  scope=observation.scope, metrics=metrics, failures=failures,
                  observation_sha256=digest(value), error_type=error_type,
                  error_code=error_code, error_stage=error_stage,
                  judge_diagnostics=getattr(judge, "diagnostics", []) if case.oracle.semantic else [],
                  gold_label=case.oracle.label, predicted_label=observation.label,
                  identity_expected=case.oracle.identity_ids is not None)


def evaluate_one(case, root, user, judge, key, observer) -> Result:
    started = time.perf_counter()
    if case.oracle.semantic and getattr(judge, "mode", None) == "provider" and judge.usage["logical_requests"] >= judge.request_budget:
        return Result(key=key, case_id=case.case_id, group_id=case.group_id, domain=case.domain, layer=case.layer,
                      status="judge_error", failures=["judge_error"], error_type="JudgeError",
                      error_code="request_budget_exhausted", error_stage="budget")
    try:
        observation = observer(case, root, user)
        result = score(case, observation, judge, key)
    except Exception as exc:
        result = Result(key=key, case_id=case.case_id, group_id=case.group_id,
                        domain=case.domain, layer=case.layer, status="error",
                        failures=["execution_error"], error_type=type(exc).__name__,
                        gold_label=case.oracle.label, identity_expected=case.oracle.identity_ids is not None)
        if isinstance(exc, EvaluationHTTPError):
            result.error_code = exc.code
            result.error_stage = exc.stage
            result.execution_diagnostic = dict(exc.diagnostic)
    result.elapsed_ms = (time.perf_counter() - started) * 1000
    return result
