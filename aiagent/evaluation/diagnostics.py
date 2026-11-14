from __future__ import annotations

import json
import os
import re
from pathlib import Path

from aiagent.common.log_safety import is_sensitive_key, sanitize_log_value
from aiagent.evaluation.contracts import digest


class LocalJudgeDebug:
    """Explicit, private, redacted local artifacts, separate from public reports."""

    def __init__(self, directory: Path):
        if os.environ.get("APP_ENV") != "local" or os.environ.get("CLOUD_MODE", "false").lower() not in {"false", "0"}:
            raise ValueError("judge debug artifacts require explicit local mode")
        self.directory = directory
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)

    def write(self, key: str, attempt: int, payload: dict, raw_verdict: str) -> None:
        value = {"payload_sha256": digest(payload), "payload": payload, "raw_verdict": raw_verdict}
        self._write(f"{digest(key)[:24]}-{attempt}.json", value)

    def write_input(self, key: str, payload: dict) -> None:
        """Keep review material even when the first judge request fails."""
        self._write(f"{digest(key)[:24]}-input.json", {
            "artifact_type": "semantic-review-input-v1", "key_sha256": digest(key),
            "payload_sha256": digest(payload), "payload": payload,
            "human_accepted": False, "baseline_eligible": False,
            "automatic_replay_allowed": False,
        })

    def _write(self, filename: str, value: dict) -> None:
        # Replace known credentials even when a model echoes a bare value without a label.
        secrets = sorted({v for k, v in os.environ.items() if v and is_sensitive_key(k)}, key=len, reverse=True)
        def replace_known(item):
            if isinstance(item, str):
                for secret in secrets:
                    item = item.replace(secret, "[redacted]")
                return re.sub(r"\b(?:sk-|gh[pousr]_|github_pat_)[a-z0-9_-]{8,}\b", "[redacted]", item, flags=re.IGNORECASE)
            if isinstance(item, dict):
                return {replace_known(k): replace_known(v) for k, v in item.items()}
            if isinstance(item, list):
                return [replace_known(v) for v in item]
            return item

        cleaned = sanitize_log_value(replace_known(value), max_depth=12, max_items=100, max_text_length=32768)
        if value.get("artifact_type") == "semantic-review-input-v1":
            cleaned["stored_payload_sha256"] = digest(cleaned["payload"])
            cleaned["payload_transformed"] = cleaned["stored_payload_sha256"] != value["payload_sha256"]
        path = self.directory / filename
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as stream:
            json.dump(cleaned, stream, ensure_ascii=False, indent=2, allow_nan=False)
