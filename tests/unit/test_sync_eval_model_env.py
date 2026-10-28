from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values

from scripts.sync_eval_model_env import build_eval_values, sync


def test_model_sync_keeps_services_but_isolates_state():
    values = build_eval_values({
        "OPENAI_API_KEY": "fixture-key",
        "OPENAI_BASE_URL": "https://api.deepseek.com",
        "LLM_MODEL": "deepseek-flash",
        "VISION_API_KEY_ENV": "OPENAI_API_KEY",
        "VISION_CHARACTER_EMBEDDING_MODEL_PATH": r"F:\aiagent\data\models\clip",
        "RAG_EMBEDDING_BASE_URL": "https://api.siliconflow.cn/v1",
        "QDRANT_HOST": "production-host",
        "NEO4J_PASSWORD": "must-not-copy",
        "CLOUD_ADMIN_TOKEN": "must-not-copy",
        "EVAL_JUDGE_API_KEY": "must-not-copy",
        "MEMORY_ENABLE_GRAPH": "true",
    }, Path("/isolated/workspace"), Path("/isolated/workspace/data/eval"))
    assert values["OPENAI_API_KEY"] == "fixture-key"
    assert values["OPENAI_BASE_URL"] == "https://api.deepseek.com"
    assert values["RAG_EMBEDDING_BASE_URL"] == "https://api.siliconflow.cn/v1"
    assert values["QDRANT_PORT"] == "16333"
    assert values["MEMORY_ENABLE_GRAPH"] == "false"
    assert values["MEMORY_VECTOR_COLLECTION"].startswith("aiagent_eval_")
    assert "NEO4J_PASSWORD" not in values
    assert "CLOUD_ADMIN_TOKEN" not in values
    assert "EVAL_JUDGE_API_KEY" not in values
    assert values["VISION_CHARACTER_EMBEDDING_MODEL_PATH"].replace("\\", "/") == "/mnt/f/aiagent/data/models/clip"


def test_sync_rejects_direct_secret_reference():
    with pytest.raises(ValueError, match="VISION_API_KEY_ENV"):
        build_eval_values({"VISION_API_KEY_ENV": "sk-fixture-secret"}, Path("/tmp/w"), Path("/tmp/w/d"))


def test_sync_writes_literal_values_and_preserves_existing_judge(tmp_path):
    source = tmp_path / "local.env"
    source.write_text("OPENAI_API_KEY='fixture-$key'\nVISION_API_KEY_ENV=OPENAI_API_KEY\n", encoding="utf-8")
    workspace = tmp_path / "isolated"
    workspace.mkdir()
    (workspace / "pyproject.toml").touch()
    dataset = workspace / "data/evaluation/frozen"
    (dataset / "reference-gallery").mkdir(parents=True)
    (workspace / ".env").write_text("EVAL_JUDGE_MODEL=keep-judge\n", encoding="utf-8")
    sync(source, workspace, dataset)
    values = dotenv_values(workspace / ".env", interpolate=False)
    assert values["OPENAI_API_KEY"] == "fixture-$key"
    assert values["EVAL_JUDGE_MODEL"] == "keep-judge"
    profile = (workspace / ".env.eval-models.sh").read_text(encoding="utf-8")
    assert "export OPENAI_API_KEY='fixture-$key'" in profile
    assert "EVAL_JUDGE_MODEL" not in profile
    assert "source " not in profile
