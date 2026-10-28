#!/usr/bin/env bash
# Section-three preflight only: no pytest, evaluator, providers or API requests.
set -euo pipefail
workspace="${1:?Pass the existing isolated workspace path}"
source "$workspace/.eval-session.sh"
cd -- "$WORKSPACE"
audit_status=0
syntax_status=0
import_status=0
docker_status=0
python scripts/audit_project_eval_data.py \
    --dataset-dir "$DS" --source-root "$SOURCE" --adapters \
    --output "$REPORTS/data-audit-wsl.json" \
    > "$REPORTS/data-audit-console.log" 2>&1 || audit_status=$?
python -m compileall -q aiagent/evaluation scripts/build_project_agent_eval_dataset.py \
    scripts/audit_project_eval_data.py tests/unit tests/api/test_evaluation_http_contract.py tests/integration \
    > "$REPORTS/syntax-preflight.log" 2>&1 || syntax_status=$?
python -c 'import aiagent.evaluation.cli; import aiagent.evaluation.load; import aiagent.evaluation.telemetry; print("Evaluation modules imported successfully")' \
    > "$REPORTS/import-preflight.log" 2>&1 || import_status=$?
docker version > "$REPORTS/docker-version.txt" 2>&1 || docker_status=$?
uv pip freeze > "$REPORTS/python-packages.txt"
python - "$audit_status" "$syntax_status" "$import_status" "$docker_status" <<'PY'
import importlib.metadata
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

statuses = dict(zip(("data_and_adapter_check", "syntax_check", "module_import_check", "docker_check"), map(int, sys.argv[1:])))
workspace = Path(os.environ["WORKSPACE"])
report = {
    "recorded_at_utc": datetime.now(UTC).isoformat(),
    "distribution": "sp3-build", "linux_user": "root", "workspace": str(workspace),
    "source": os.environ["SOURCE"], "dataset": os.environ["DS"], "reports": os.environ["REPORTS"],
    "session_script": str(workspace / ".eval-session.sh"),
    "python": platform.python_version(), "platform": platform.system(),
    "torch": importlib.metadata.version("torch"), "psutil": importlib.metadata.version("psutil"),
    "exit_codes": statuses, "section_three_complete": all(value == 0 for value in statuses.values()),
    "docker_access": "Windows Docker CLI bridge; native WSL integration not enabled",
    "tests_executed": False, "providers_called": False, "evaluation_api_requests_sent": 0,
    "note": "Dependency downloads and local Docker version checks occurred; no evaluations or test cases ran.",
}
outputs = [Path(os.environ["REPORTS"]) / "environment-setup.json",
           Path(os.environ["SOURCE"]) / "data/cache/evaluation-environments" / (workspace.name + "-ready.json")]
for path in outputs:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
PY
if (( audit_status || syntax_status || import_status || docker_status )); then
    printf 'Preflight failed; inspect logs under %s\n' "$REPORTS" >&2
    exit 1
fi
