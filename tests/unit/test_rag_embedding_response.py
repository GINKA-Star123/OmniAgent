from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from aiagent.knowledge.vector_store import EmbeddingValidationError, OpenAICompatibleEmbeddings


def embed(response, texts=None, dimensions=2):
    embeddings = OpenAICompatibleEmbeddings("fixture", "offline-placeholder", "https://offline.invalid/v1",
                                           dimensions=dimensions)
    embeddings.client.close()
    with OpenAI(api_key="offline-placeholder", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)))) as client:
        embeddings.client = client
        return embeddings.embed_documents(texts or ["fixture"])


def test_out_of_order_response_is_sorted():
    assert embed({"data": [{"index": 1, "embedding": [0.2, 0.3]}, {"index": 0, "embedding": [0.4, 0.5]}]},
                 texts=["first", "second"]) == [[0.4, 0.5], [0.2, 0.3]]


@pytest.mark.parametrize("data, message", [
    ([], "count"),
    ([{"index": 1, "embedding": [0.1, 0.2]}], "indexes"),
    ([{"index": 0, "embedding": [0.1]}], "dimension"),
    ([{"index": 0, "embedding": "invalid-base64-vector"}], "dimension"),
    ([{"index": 0, "embedding": [0.1, "bad"]}], "finite"),
    ([{"index": 0, "embedding": [0.1, True]}], "finite"),
])
def test_invalid_vectors_rejected_before_native_index(data, message):
    with pytest.raises(ValueError, match=message):
        embed({"data": data})


def test_duplicate_response_indexes_rejected():
    with pytest.raises(ValueError, match="indexes"):
        embed({"data": [{"index": 0, "embedding": [0.1, 0.2]}] * 2}, texts=["a", "b"])


def test_32_response_grouped_indexes_rejected_with_safe_indexes():
    data = [{"index": i % 8, "embedding": [0.1, 0.2]} for i in range(32)]
    with pytest.raises(EmbeddingValidationError) as error:
        embed({"data": data}, texts=[f"private-input-{i}" for i in range(32)])
    assert error.value.code == "embedding_response_index_mismatch"
    assert error.value.details["actual_indexes"] == sorted(i % 8 for i in range(32))
    assert "private-input" not in json.dumps(error.value.details)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_vector_rejected(value):
    embeddings = OpenAICompatibleEmbeddings("fixture", "offline-placeholder", "https://offline.invalid/v1", dimensions=2)
    embeddings.client.close()
    embeddings.client = SimpleNamespace(embeddings=SimpleNamespace(with_raw_response=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(content=json.dumps({"data": [{"index": 0, "embedding": [value, 0.1]}]})),
    )))
    with pytest.raises(ValueError, match="finite"):
        embeddings.embed_documents(["fixture"])


@pytest.mark.parametrize("data, code", [
    (None, "embedding_response_count_mismatch"),
    ([], "embedding_response_count_mismatch"),
    ([{"embedding": [0.1, 0.2]}], "embedding_response_index_type"),
    ([{"index": True, "embedding": [0.1, 0.2]}], "embedding_response_index_type"),
    ([{"index": "0", "embedding": [0.1, 0.2]}], "embedding_response_index_type"),
    ([{"index": 5, "embedding": [0.1, 0.2]}], "embedding_response_index_mismatch"),
    ([{"index": 0, "embedding": [0.1]}], "embedding_response_dimension_mismatch"),
    ([{"index": 0, "embedding": "private-response-sentinel"}], "embedding_response_vector_type"),
    ([{"index": 0, "embedding": [True, 0.2]}], "embedding_response_nonfinite_or_nonnumeric"),
])
def test_protocol_errors_have_distinct_safe_diagnostics(data, code):
    with pytest.raises(EmbeddingValidationError) as error:
        embed({"data": data})
    assert error.value.code == code
    details = error.value.details
    assert details["validation_stage"] == "response_validation"
    assert details["expected_count"] == 1
    assert details["expected_dimensions"] == 2
    assert details["batch_number"] == details["total_batches"] == 1
    assert "private-response-sentinel" not in json.dumps(details)


def test_dimension_error_reports_actual_dimension_without_vector_values():
    with pytest.raises(EmbeddingValidationError) as error:
        embed({"data": [{"index": 0, "embedding": [0.1234567] * 1024}]}, dimensions=4096)
    assert error.value.details["expected_dimensions"] == 4096
    assert error.value.details["actual_dimensions"] == 1024
    assert "0.1234567" not in json.dumps(error.value.details)


def test_invalid_json_has_safe_error_code():
    embeddings = OpenAICompatibleEmbeddings("fixture", "offline-placeholder", "https://offline.invalid/v1", dimensions=2)
    embeddings.client.close()
    with OpenAI(api_key="offline-placeholder", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, content=b"private-response-not-json")))) as client:
        embeddings.client = client
        with pytest.raises(EmbeddingValidationError) as error:
            embeddings.embed_documents(["private-input-sentinel"])
    assert error.value.code == "embedding_response_invalid_json"
    assert "private" not in str(error.value) + json.dumps(error.value.details)


def test_sdk_value_error_has_request_stage_without_exposing_message():
    embeddings = OpenAICompatibleEmbeddings("fixture", "offline-placeholder", "https://offline.invalid/v1", dimensions=2)
    embeddings.client.close()

    def reject(**kwargs):
        raise ValueError("private-sdk-secret-sentinel")

    embeddings.client = SimpleNamespace(embeddings=SimpleNamespace(with_raw_response=SimpleNamespace(create=reject)))
    with pytest.raises(EmbeddingValidationError) as error:
        embeddings.embed_documents(["private-input-sentinel"])
    assert error.value.code == "embedding_request_value_error"
    assert error.value.details["validation_stage"] == "request"
    assert "private" not in str(error.value) + json.dumps(error.value.details)
    from scripts.rebuild_rag_cache import safe_failure

    safe = safe_failure(error.value)
    assert safe["cause_type"] == "ValueError"
    assert safe["cause_locations"][-1]["function"] == "reject"
    assert "private-sdk-secret-sentinel" not in json.dumps(safe)
