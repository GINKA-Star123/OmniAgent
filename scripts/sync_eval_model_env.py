"""Copy model settings into an isolated WSL workspace without running models."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import tempfile
from pathlib import Path, PureWindowsPath

from dotenv import dotenv_values, set_key

MODEL_PREFIXES = ("LLM_", "STATE_", "PLANNER_", "RAG_", "MEMORY_", "VISION_")
MODEL_KEYS = {
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "SILICONFLOW_API", "SILICONFLOW_BASE_URL",
    "ENABLE_MOCK_LLM", "ENABLE_MOCK_STATE", "ENABLE_MOCK_PLANNER",
}


def build_eval_values(source: dict, workspace: Path, dataset: Path) -> dict[str, str]:
    values = {
        key: str(value or "")
        for key, value in source.items()
        if key in MODEL_KEYS or key.startswith(MODEL_PREFIXES)
    }
    for key, value in tuple(values.items()):
        if not key.endswith("_API_KEY_ENV") or not value:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError(f"{key} must contain a variable name, not a secret")
        values[value] = str(source.get(value) or "")

    clip_path = values.get("VISION_CHARACTER_EMBEDDING_MODEL_PATH", "")
    windows_path = PureWindowsPath(clip_path)
    if windows_path.drive and re.fullmatch(r"[A-Za-z]:", windows_path.drive):
        clip_path = str(Path("/mnt") / windows_path.drive[0].lower() / Path(*windows_path.parts[1:]))
    values["VISION_CHARACTER_EMBEDDING_MODEL_PATH"] = clip_path

    scope = re.sub(r"[^A-Za-z0-9_]", "_", workspace.name)
    values.update({
        "APP_ENV": "local", "CLOUD_MODE": "false",
        "REDIS_URL": "redis://127.0.0.1:16379/0", "REDIS_PREFIX": f"aiagent:eval:{scope}",
        "EXECUTION_STATE_MODE": "redis", "EXECUTION_STATE_FAIL_CLOSED": "true",
        "QDRANT_HOST": "127.0.0.1", "QDRANT_PORT": "16333",
        "MEMORY_VECTOR_COLLECTION": f"aiagent_eval_{scope}",
        "MEMORY_ENABLE_GRAPH": "false", "MEMORY_RESET_VECTOR_STORE": "false",
        "MEMORY_WRITE_ASYNC_ENABLED": "false",
        "MEMORY_PREFERENCES_PATH": str(workspace / "data/runtime/eval-memory-preferences.json"),
        "RAG_AUTO_REBUILD_ON_STALE": "false",
        "RAG_INDEX_MANIFEST_PATH": str(workspace / "data/cache/knowledge/index_manifest.json"),
        "VISION_UPLOAD_DIR": str(workspace / "data/uploads/eval-images"),
        "VISION_CHARACTER_ROOT_DIR": str(dataset / "reference-gallery"),
        "VISION_CHARACTER_INDEX_DIR": str(workspace / "data/cache/vision/eval-character-index"),
        "VISION_CHARACTER_EMBEDDING_DEVICE": "cpu",
        "API_CORS_ORIGINS": "http://127.0.0.1:3000,http://localhost:3000",
        "API_CORS_ALLOW_CREDENTIALS": "true",
        "RATE_LIMIT_ENABLED": "false", "INFLIGHT_LIMIT_ENABLED": "false",
        "TTS_PROVIDER": "mock", "ENABLE_MOCK_TTS": "true",
        "ASR_PROVIDER": "mock", "ENABLE_MOCK_ASR": "true",
        "ENABLE_LOCAL_AUDIO_PLAYBACK": "false",
    })
    return values


def write_private(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            os.chmod(temporary, 0o600)
            handle.write(content)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sync(source: Path, workspace: Path, dataset: Path) -> int:
    source = source.resolve(strict=True)
    workspace = workspace.resolve(strict=True)
    dataset = dataset.resolve(strict=True)
    destination = workspace / ".env"
    if source == destination or not (workspace / "pyproject.toml").is_file():
        raise ValueError("Destination must be a separate project workspace")
    if not dataset.is_relative_to(workspace) or not (dataset / "reference-gallery").is_dir():
        raise ValueError("Dataset must be frozen inside the isolated workspace")
    values = build_eval_values(dict(dotenv_values(source, interpolate=False)), workspace, dataset)
    existing = dict(dotenv_values(destination, interpolate=False)) if destination.exists() else {}
    existing.update(values)
    # dotenv quoting and Bash quoting are different; never source a dotenv file.
    with tempfile.TemporaryDirectory(dir=workspace) as temporary:
        staged = Path(temporary) / ".env"
        staged.touch(mode=0o600)
        for key, value in existing.items():
            set_key(staged, key, str(value or ""), quote_mode="always")
        write_private(destination, staged.read_text(encoding="utf-8"))
    exports = ["# Generated private model profile. Source only after offline setup.", "unset OPENROUTER_API_KEY"]
    exports.extend(f"export {key}={shlex.quote(value)}" for key, value in sorted(values.items()))
    write_private(workspace / ".env.eval-models.sh", "\n".join(exports) + "\n")
    return len(values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path)
    args = parser.parse_args()
    count = sync(args.source, args.workspace, args.dataset)
    print(f"Synchronized {count} settings; private files mode 600. No model requests executed.")


if __name__ == "__main__":
    main()
