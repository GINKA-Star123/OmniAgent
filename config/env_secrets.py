"""Resolve named secrets using the same dotenv location as Settings."""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import dotenv_values


def resolve_named_secret(name: str) -> str | None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return None
    # An explicitly empty process variable disables the dotenv fallback.
    if name in os.environ:
        return os.environ[name].strip() or None
    path = Path(".env")
    if not path.is_file():
        return None
    value = dotenv_values(path, encoding="utf-8-sig", interpolate=False).get(name)
    if value is None:
        return None
    return value.strip() or None
