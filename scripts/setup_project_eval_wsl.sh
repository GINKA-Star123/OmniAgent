#!/usr/bin/env bash
# Prepare only the isolated workspace and dependencies; never run evaluations.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
source_root=/mnt/f/aiagent
dataset_relative=data/evaluation/project-20261026-r3
for executable in git rsync curl jq python3 uv; do
    command -v "$executable" >/dev/null || { printf 'Missing tool: %s\n' "$executable" >&2; exit 1; }
done
for package in python3-venv git rsync curl jq ffmpeg libgl1 libglib2.0-0t64 libgomp1 libportaudio2; do
    dpkg-query -W -f='${Status}' "$package" | grep -qx 'install ok installed' || {
        printf 'Missing system package: %s\n' "$package" >&2
        exit 1
    }
done
test -f "$source_root/$dataset_relative/manifest.json"
mkdir -p -- "$HOME/aiagent-eval"
workspace="$(mktemp -d "$HOME/aiagent-eval/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
printf 'WORKSPACE=%s\n' "$workspace"
rsync -a \
    --include='/.env.example' --include='/cloud.tencent.example.env' \
    --exclude='/.git' --exclude='/.venv*' --exclude='/data/' \
    --exclude='/.env*' --exclude='/cloud*.env' \
    --exclude='__pycache__/' --exclude='/.pytest_cache/' \
    --exclude='/_tmp/' --exclude='/.ruff_cache/' --exclude='/.vscode/' --exclude='/aiagent.egg-info/' \
    --exclude='/third_party/' --exclude='/gpu_services/' \
    --exclude='/apps/flutter_client/' --exclude='/apps/desktop_qt/' \
    "$source_root/" "$workspace/"
mkdir -p -- "$workspace/data/evaluation" "$workspace/data/knowledge/public" "$workspace/data/persona"
cp -a -- "$source_root/$dataset_relative" "$workspace/data/evaluation/"
cp -a -- "$workspace/$dataset_relative/corpus/public/." "$workspace/data/knowledge/public/"
cp -a -- "$workspace/$dataset_relative/persona/yzl" "$workspace/data/persona/"
cp -- "$workspace/scripts/project_eval_session.sh" "$workspace/.eval-session.sh"
cd -- "$workspace"
git init -q
git add aiagent apps cloud config integrations scripts tests docs deploy pyproject.toml uv.lock .gitignore
git -c core.hooksPath=/dev/null -c user.name='Local Evaluation Snapshot' \
    -c user.email='eval@example.invalid' commit -q -m 'local evaluation source snapshot'
source "$workspace/.eval-session.sh"
git rev-parse HEAD > "$REPORTS/source-commit.txt"
sha256sum "$DS/manifest.json" "$DS/corpus-manifest.json" > "$REPORTS/dataset-hashes.txt"
python3 - "$workspace" "$source_root" <<'PY'
import json
import sys
from pathlib import Path

workspace, source = map(Path, sys.argv[1:])
record = {
    "distribution": "sp3-build", "user": "root", "workspace": str(workspace),
    "source": str(source), "dataset": str(workspace / "data/evaluation/project-20261026-r3"),
    "session_script": str(workspace / ".eval-session.sh"),
    "status": "workspace_created_dependency_setup_pending",
    "tests_executed": False, "providers_called": False,
}
path = source / "data/cache/evaluation-environments" / (workspace.name + ".json")
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("x", encoding="utf-8") as stream:
    json.dump(record, stream, ensure_ascii=False, indent=2)
print("WORKSPACE_RECORD=" + str(path))
PY
uv python install 3.12
uv sync --locked --extra dev --python 3.12
source "$workspace/.venv/bin/activate"
uv pip install psutil
uv pip freeze > "$REPORTS/python-packages.txt"
python -V
printf 'PREPARATION_COMPLETE=%s\n' "$workspace"
