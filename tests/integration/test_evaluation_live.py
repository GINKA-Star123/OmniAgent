import os
import uuid
from pathlib import Path

import pytest

from aiagent.evaluation.adapters import observe
from aiagent.evaluation.contracts import Dataset, read_json
from scripts.build_agent_eval_dataset import api_dataset

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EVAL_RUN_LIVE") != "1", reason="requires explicit isolated deployment",
)]


def test_real_memory_control_state_and_delete(tmp_path):
    dataset = Dataset.model_validate(api_dataset())
    for case in dataset.cases:
        user = f"eval-live-{uuid.uuid4().hex}"
        observation = observe(case, tmp_path, user)
        assert observation.scope == "isolated_api"
        assert observation.answer.strip()
        for term in case.oracle.forbidden_terms:
            assert term not in observation.answer


def test_real_image_upload_when_requested():
    raw = os.environ.get("EVAL_VISION_DATASET")
    if not raw:
        pytest.fail("live suite requires EVAL_VISION_DATASET pointing to real annotated images")
    path = Path(raw).resolve()
    dataset = Dataset.model_validate(read_json(path))
    cases = [case for case in dataset.cases if case.kind == "vision_api"]
    assert cases, "no real image cases"
    for case in cases:
        observation = observe(case, path.parent, f"eval-live-{uuid.uuid4().hex}")
        assert observation.scope == "real_image_api"
        if case.oracle.label is not None:
            assert observation.label == case.oracle.label
        assert observation.data["evaluation_images"]
