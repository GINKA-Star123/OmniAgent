# Source this file from an isolated evaluation workspace, not from scripts/.
_eval_workspace="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ ! -f "$_eval_workspace/pyproject.toml" || ! -d "$_eval_workspace/data/evaluation/project-20261026-r3" ]]; then
    printf '%s\n' 'Evaluation workspace layout not found; source WORKSPACE/.eval-session.sh.' >&2
    unset _eval_workspace
    return 1
fi
export WORKSPACE="$_eval_workspace"
export SOURCE=/mnt/f/aiagent
export STAMP="$(basename -- "$WORKSPACE")"
export DS_REL=data/evaluation/project-20261026-r3
export DS="$WORKSPACE/$DS_REL"
export REPORTS="$WORKSPACE/data/cache/reports/project-eval-$STAMP"
export UV_PROJECT_ENVIRONMENT="$WORKSPACE/.venv"
export PATH="$HOME/.local/bin:$PATH"
if command -v docker.exe >/dev/null 2>&1 && ! command docker version >/dev/null 2>&1; then
    docker() { command docker.exe "$@"; }
    export -f docker
fi
export PYTHONUTF8=1
export APP_ENV=local CLOUD_MODE=false EXECUTION_STATE_MODE=local
export LLM_PROVIDER=mock ENABLE_MOCK_LLM=true
export STATE_PROVIDER=mock ENABLE_MOCK_STATE=true
export PLANNER_PROVIDER=mock ENABLE_MOCK_PLANNER=true
export VISION_PROVIDER=mock
# Explicit empties block named-secret fallback to the private model dotenv.
export OPENAI_API_KEY= SILICONFLOW_API= EVAL_OFFLINE_MEMORY_KEY=
export MEMORY_LLM_API_KEY_ENV=EVAL_OFFLINE_MEMORY_KEY
export RAG_EMBEDDING_PROVIDER=huggingface RAG_EMBEDDING_LOCAL_FILES_ONLY=true
export TTS_PROVIDER=mock ENABLE_MOCK_TTS=true ENABLE_LOCAL_AUDIO_PLAYBACK=false
export ASR_PROVIDER=mock ENABLE_MOCK_ASR=true
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
unset EVAL_RUN_LIVE EVAL_BASE_URL EVAL_ISOLATED EVAL_JUDGE_API_KEY EVAL_JUDGE_VISION
cd -- "$WORKSPACE" || return 1
mkdir -p -- "$REPORTS"
if [[ -f "$WORKSPACE/.venv/bin/activate" ]]; then
    source "$WORKSPACE/.venv/bin/activate"
else
    printf '%s\n' 'Linux venv is not ready; finish uv sync before running evaluations.' >&2
fi
printf 'WORKSPACE=%s\nDS=%s\nREPORTS=%s\nMode=offline/mock; no service started\n' "$WORKSPACE" "$DS" "$REPORTS"
unset _eval_workspace
