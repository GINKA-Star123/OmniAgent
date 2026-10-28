from __future__ import annotations

import asyncio
import mimetypes
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import Field, model_validator

from aiagent.evaluation.contracts import Check, StrictModel, check_value


class EvaluationHTTPError(Exception):
    def __init__(self, code: str, *, status: int | None = None, failed_checks: list[int] | None = None):
        super().__init__(code)
        self.code = code
        self.stage = "api_step"
        self.diagnostic = {"last_status": status, "failed_check_indices": failed_checks or []}


class EvaluationPollTimeout(EvaluationHTTPError, TimeoutError):
    pass


class EvaluationAssertionError(EvaluationHTTPError, AssertionError):
    pass

def asset(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("asset must be an existing file under the dataset directory")
    return path

def substitute(value, user: str):
    if isinstance(value, str):
        return value.replace("{user}", user)
    if isinstance(value, list):
        return [substitute(item, user) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, user) for key, item in value.items()}
    return value

class Step(StrictModel):
    method: str = "POST"
    path: str
    body: dict = Field(default_factory=dict)
    image: str | None = None
    image_sha256: str | None = None
    expected_status: int = Field(default=200, ge=100, le=599)
    checks: list[Check] = Field(default_factory=list)
    timeout: float = Field(default=60, gt=0, le=600)
    poll_seconds: float = Field(default=0, ge=0, le=600)
    capture: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        self.method = self.method.upper()
        if self.method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("unsupported HTTP method")
        parsed = urlsplit(self.path)
        if not self.path.startswith("/") or self.path.startswith("//") or parsed.scheme or parsed.netloc:
            raise ValueError("relative API path required")
        if "\\" in self.path or "/.." in self.path or "%" in self.path:
            raise ValueError("encoded or traversing paths not accepted")
        if self.poll_seconds and self.method != "GET":
            raise ValueError("poll only idempotent GET requests")
        if not self.checks:
            raise ValueError("HTTP 200 alone is not a success oracle")
        if self.image and (self.method != "POST" or not self.image_sha256):
            raise ValueError("image upload requires POST and pinned SHA256")
        import re

        if any(not re.fullmatch(r"id_[a-z0-9_]+", key) or not value.startswith("/")
               for key, value in self.capture.items()):
            raise ValueError("capture requires id_ names and JSON pointers")
        return self

async def one_request(client: httpx.AsyncClient, step: Step, root: Path) -> tuple[int, dict]:
    async def request():
        if step.image:
            import hashlib

            path = asset(root, step.image)
            raw = path.read_bytes()
            if len(raw) > 20 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != step.image_sha256:
                raise ValueError("image size/hash mismatch")
            response = await client.request(
                step.method, step.path, data={key: str(value) for key, value in step.body.items()},
                files={"file": (path.name, raw, mimetypes.guess_type(path.name)[0] or "application/octet-stream")},
            )
        else:
            kwargs = {"params": step.body} if step.method == "GET" else {"json": step.body}
            response = await client.request(step.method, step.path, **kwargs)
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("expected JSON object")
        return response.status_code, data

    return await asyncio.wait_for(request(), timeout=step.timeout)

async def execute_step(client, step: Step, root: Path) -> dict:
    deadline = time.perf_counter() + (step.poll_seconds or step.timeout)
    status = None
    failed_checks = []
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise EvaluationPollTimeout("api_poll_timeout", status=status, failed_checks=failed_checks)
        bounded = step.model_copy(update={"timeout": min(step.timeout, remaining)})
        try:
            status, data = await one_request(client, bounded, root)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise EvaluationPollTimeout("api_request_timeout", status=status, failed_checks=failed_checks) from exc
        failed_checks = [index for index, check in enumerate(step.checks, start=1) if not check_value(data, check)]
        passed = status == step.expected_status and not failed_checks
        if passed:
            return {"status": status, "body": data}
        if not step.poll_seconds:
            raise EvaluationAssertionError("api_assertion_failed", status=status, failed_checks=failed_checks)
        await asyncio.sleep(min(0.2, max(0.0, deadline - time.perf_counter())))

def require_isolated() -> str:
    base = os.environ.get("EVAL_BASE_URL", "")
    parsed = urlsplit(base)
    if os.environ.get("EVAL_ISOLATED", "") != "1" or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("explicit isolated EVAL_BASE_URL and EVAL_ISOLATED=1 required")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("API base must be an origin without credentials or path")
    return base.rstrip("/")

async def run_steps(raw_steps: list[dict], cleanup: list[dict], root: Path, user: str) -> list[dict]:
    import re

    from aiagent.evaluation.contracts import pointer

    base = require_isolated()
    if not user.startswith("eval-"):
        raise ValueError("evaluation namespace required")
    steps = [Step.model_validate(substitute(raw, user)) for raw in raw_steps]
    finalizers = [Step.model_validate(substitute(raw, user)) for raw in cleanup]
    for step in [*steps, *finalizers]:
        if step.path.startswith("/memory/user/") and not step.path.startswith(f"/memory/user/{user}/") and step.path != f"/memory/user/{user}":
            raise ValueError("cross-user path outside this evaluation namespace")
        if step.method != "GET" and step.body.get("user_id", user) != user:
            raise ValueError("cross-user request body")
        allowed = ("/chat", "/chat/multimodal", "/vision/analyze", "/vision/chat", "/knowledge/search")
        if not step.path.startswith(f"/memory/user/{user}") and step.path not in allowed:
            raise ValueError("endpoint not allowed by evaluation adapter")
    rows = []
    captures = {}

    def expand(value):
        if isinstance(value, str):
            return re.sub(r"\{(id_[a-z0-9_]+)\}", lambda match: captures[match.group(1)], value)
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            return {key: expand(item) for key, item in value.items()}
        return value

    async def execute(step):
        resolved = Step.model_validate(expand(step.model_dump(mode="json")))
        row = await execute_step(client, resolved, root)
        for name, path in resolved.capture.items():
            value = pointer(row, path)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
                raise ValueError("captured ID is missing or unsafe")
            captures[name] = value
        return row

    headers = {}
    if os.environ.get("EVAL_API_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['EVAL_API_TOKEN']}"
    async with httpx.AsyncClient(base_url=base, headers=headers, trust_env=False,
                                 follow_redirects=False, timeout=60.0) as client:
        try:
            for index, step in enumerate(steps, start=1):
                try:
                    rows.append(await execute(step))
                except EvaluationHTTPError as exc:
                    exc.stage = f"api_step_{index}"
                    exc.diagnostic.update(step_index=index, method=step.method)
                    raise
        finally:
            # Cleanup is part of success, not a best-effort operation silently ignored.
            cleanup_errors = []
            for step in finalizers:
                try:
                    await execute(step)
                except Exception as exc:
                    cleanup_errors.append(type(exc).__name__)
            if cleanup_errors:
                raise RuntimeError("evaluation cleanup failed")
    return rows
