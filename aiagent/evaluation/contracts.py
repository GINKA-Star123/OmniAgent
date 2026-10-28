from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def read_json(path: Path) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"nonfinite JSON number: {value}")

    return json.loads(path.read_text(encoding="utf-8-sig"),
                      object_pairs_hook=unique, parse_constant=invalid)

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Check(StrictModel):
    pointer: str = Field(pattern=r"^(/.*)?$")
    op: Literal["eq", "contains", "text_contains", "text_absent", "absent", "ge", "le"] = "eq"
    value: Any = None

class Limit(StrictModel):
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.minimum is None and self.maximum is None:
            raise ValueError("metric limit must specify a bound")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("inverted metric bounds")
        return self

class Oracle(StrictModel):
    checks: list[Check] = Field(default_factory=list)
    required_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    relevance: dict[str, int] = Field(default_factory=dict)
    ks: list[int] = Field(default_factory=lambda: [1, 3, 5, 10])
    label: str | None = None
    ocr: str | None = None
    identity_ids: list[str] | None = None
    required_events: list[str] = Field(default_factory=list)
    forbidden_events: list[str] = Field(default_factory=list)
    before: list[tuple[str, str]] = Field(default_factory=list)
    semantic: bool = False
    gold: dict[str, str] = Field(default_factory=dict)
    rubric: str = "事实、安全、用户要求优先于角色风格。"
    limits: dict[str, Limit] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        if not self.ks or any(type(k) is not int or k < 1 for k in self.ks) or len(set(self.ks)) != len(self.ks):
            raise ValueError("ks must contain unique positive integers")
        if any(type(v) is not int or v < 0 or v > 4 for v in self.relevance.values()):
            raise ValueError("relevance grades must be integers from 0 to 4")
        if any(not x.strip() for x in (*self.required_terms, *self.forbidden_terms)):
            raise ValueError("blank answer rule")
        if set(self.required_terms) & set(self.forbidden_terms):
            raise ValueError("contradictory answer rules")
        if self.semantic and (not self.gold or any(not k.strip() or not v.strip() for k, v in self.gold.items())):
            raise ValueError("semantic evaluation requires independent gold facts")
        if not (self.checks or self.required_terms or self.forbidden_terms or self.label is not None
                or self.ocr is not None or self.identity_ids is not None or self.required_events or self.forbidden_events or self.before or self.limits):
            raise ValueError("case requires an explicit success condition")
        return self

class Case(StrictModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    group_id: str = Field(min_length=1)
    domain: Literal["rag", "memory", "vision", "persona"]
    layer: Literal["component", "trajectory", "task"]
    split: Literal["dev", "regression", "heldout", "adversarial"] = "regression"
    kind: Literal["rag", "memory", "vision_policy", "vision_api", "persona", "graph", "api"]
    inputs: dict[str, Any]
    oracle: Oracle

class Dataset(StrictModel):
    version: Literal["agent-eval-system-v1"]
    description: str
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def valid(self):
        ids = [c.case_id for c in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate case_id")
        digest(self.model_dump(mode="json"))
        return self

class Observation(StrictModel):
    scope: str
    answer: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)
    retrieved: list[str] = Field(default_factory=list)
    label: str | None = None
    ocr: str | None = None
    events: list[str] = Field(default_factory=list)

class JudgeDiagnostic(StrictModel):
    attempt: int = Field(ge=1)
    channel: Literal["combined", "visual", "gold"] = "combined"
    stage: Literal["configuration", "budget", "request", "response", "parse", "validation", "complete", "internal"]
    code: str = Field(pattern=r"^[a-z_]+$")
    finish_reason: Literal["stop", "length", "content_filter", "tool_calls", "function_call", "missing", "unknown"] = "missing"
    retryable: bool = False
    output_chars: int = Field(default=0, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)

class Result(StrictModel):
    key: str
    case_id: str
    group_id: str
    domain: str
    layer: str
    status: Literal["passed", "failed", "error", "judge_error"]
    scope: str = "unavailable"
    metrics: dict[str, float | None] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0.0
    observation_sha256: str = ""
    error_type: str = ""
    error_code: str = ""
    error_stage: str = ""
    execution_diagnostic: dict[str, Any] = Field(default_factory=dict)
    judge_diagnostics: list[JudgeDiagnostic] = Field(default_factory=list)
    gold_label: str | None = None
    predicted_label: str | None = None
    identity_expected: bool = False

MISSING = object()

def pointer(value: Any, path: str) -> Any:
    if path == "":
        return value
    node = value
    for raw in path[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            node = node.get(token, MISSING)
        elif isinstance(node, list) and token.isdecimal():
            index = int(token)
            node = node[index] if index < len(node) else MISSING
        else:
            return MISSING
        if node is MISSING:
            return MISSING
    return node

def check_value(value: Any, check: Check) -> bool:
    node = pointer(value, check.pointer)
    if check.op == "absent":
        return node is MISSING
    if node is MISSING:
        return False
    if check.op == "eq":
        return type(node) is type(check.value) and node == check.value
    if check.op == "contains":
        return isinstance(node, (str, list, dict)) and check.value in node
    if check.op in {"text_contains", "text_absent"}:
        def texts(item):
            if isinstance(item, str):
                yield item
            elif isinstance(item, list):
                for child in item:
                    yield from texts(child)
            elif isinstance(item, dict):
                for child in item.values():
                    yield from texts(child)
        if not isinstance(check.value, str) or not check.value:
            return False
        present = any(check.value in text for text in texts(node))
        return present if check.op == "text_contains" else not present
    if check.op in {"ge", "le"}:
        if type(node) not in {int, float} or type(check.value) not in {int, float}:
            return False
        return node >= check.value if check.op == "ge" else node <= check.value
    return False
