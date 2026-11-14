from __future__ import annotations

import base64
from dataclasses import replace
from io import BytesIO
from struct import error as StructError

import httpx
import pytest
from PIL import GifImagePlugin, Image

from aiagent.graphs.main_graph import MainRunner
from aiagent.graphs.vision_graph import VisionRunner
from aiagent.schemas.inputs import InputAttachment, InputEvent, InputSource
from aiagent.services import vision_service as service_module
from aiagent.services.vision_service import VisionService
from aiagent.vision import gif_frames
from aiagent.vision.gif_frames import (
    DEFAULT_GIF_POLICY,
    GifPolicy,
    ImageInputError,
    gif_metadata,
    inspect_gif,
    prepare_gif_content,
    sample_indices,
)
from aiagent.vision.image_store import ImageStore


def make_gif(count=3, duration=100, size=(24, 20), disposal=2):
    frames = [
        Image.new("RGB", size, ((index * 53) % 256, 25, 255 - (index * 47) % 256))
        for index in range(count)
    ]
    with BytesIO() as buffer:
        frames[0].save(
            buffer, format="GIF", save_all=True, append_images=frames[1:],
            duration=duration, loop=0, disposal=disposal, optimize=False,
        )
        result = buffer.getvalue()
    for frame in frames:
        frame.close()
    return result


def write_gif(tmp_path, content=None):
    path = tmp_path / "input.gif"
    path.write_bytes(make_gif() if content is None else content)
    return path


class EmptyRetriever:
    def retrieve(self, image_path, top_k=5):
        return []


def make_service(tmp_path, provider="mock"):
    return VisionService(
        image_store=ImageStore(upload_dir=tmp_path / "uploads"),
        character_retriever=EmptyRetriever(),
        provider=provider, model="synthetic-multiframe-model",
        api_key="synthetic-key", base_url="https://vision.invalid/v1",
    )


@pytest.mark.parametrize("count", [1, 2, 3, 6, 7, 120])
def test_sample_indices_are_unique_ordered_and_include_ends(count):
    indices = sample_indices(count, 6)
    assert len(indices) == min(count, 6)
    assert tuple(sorted(set(indices))) == indices
    assert indices[0] == 0
    assert indices[-1] == count - 1


@pytest.mark.parametrize("signature", [b"GIF87a", b"GIF89a"])
def test_both_gif_headers_are_supported(tmp_path, signature):
    with BytesIO() as buffer:
        Image.new("RGB", (20, 20), "red").save(buffer, format="GIF")
        content = buffer.getvalue()
    path = write_gif(tmp_path, signature + content[6:])
    assert inspect_gif(path).frame_count == 1


def test_durations_and_sample_metadata(tmp_path):
    path = write_gif(tmp_path, make_gif(duration=[0, 200, 300]))
    info = inspect_gif(path)
    assert info.durations_ms == (100, 200, 300)
    metadata = gif_metadata(info)
    assert metadata["vision_gif_sample_times_ms"] == [0, 100, 300]
    assert metadata["vision_gif_duration_ms"] == 600


@pytest.mark.parametrize("policy,expected", [
    (replace(DEFAULT_GIF_POLICY, max_frames=2), "gif_frame_count_exceeded"),
    (replace(DEFAULT_GIF_POLICY, max_frame_pixels=100), "gif_frame_pixels_exceeded"),
    (replace(DEFAULT_GIF_POLICY, max_total_pixels=1000), "gif_total_pixels_exceeded"),
    (replace(DEFAULT_GIF_POLICY, max_duration_ms=250), "gif_duration_exceeded"),
    (replace(DEFAULT_GIF_POLICY, max_frame_duration_ms=100), "gif_frame_duration_exceeded"),
])
def test_budget_contrast_rejects_instead_of_partial_success(tmp_path, policy, expected):
    path = write_gif(tmp_path, make_gif(duration=200))
    assert inspect_gif(path).frame_count == 3
    with pytest.raises(ImageInputError, match=expected):
        inspect_gif(path, policy)


def test_data_url_budget_is_checked(tmp_path):
    path = write_gif(tmp_path)
    with pytest.raises(ImageInputError, match="gif_payload_exceeded"):
        prepare_gif_content(path, replace(DEFAULT_GIF_POLICY, max_data_url_chars=20))


@pytest.mark.parametrize("decode", [inspect_gif, prepare_gif_content], ids=["inspect", "prepare"])
@pytest.mark.parametrize("change", ["trailer", "middle", "wrong_header"])
def test_damaged_input_rejected(tmp_path, change, decode):
    content = make_gif()
    if change == "trailer":
        content = content[:-1]
    elif change == "middle":
        content = content[:len(content) // 2] + b";"
    else:
        content = b"NOTGIF" + content[6:]
    with pytest.raises(ImageInputError):
        decode(write_gif(tmp_path, content))


@pytest.mark.parametrize("decode", [inspect_gif, prepare_gif_content], ids=["inspect", "prepare"])
@pytest.mark.parametrize("error_type", [IndexError, StructError], ids=["index", "struct"])
def test_pillow_frame_errors_are_image_input_errors(tmp_path, monkeypatch, decode, error_type):
    path = write_gif(tmp_path)
    info = inspect_gif(path)
    if decode is prepare_gif_content:
        # Isolate the second decode pass, after the initial inspection has succeeded.
        monkeypatch.setattr(gif_frames, "inspect_gif", lambda *args, **kwargs: info)

    original_seek = GifImagePlugin.GifImageFile.seek

    def damaged_seek(image, frame):
        if frame == 1:
            raise error_type("synthetic_incomplete_gif_frame")
        return original_seek(image, frame)

    monkeypatch.setattr(GifImagePlugin.GifImageFile, "seek", damaged_seek)
    with pytest.raises(ImageInputError, match="^gif_decode_failed$") as caught:
        decode(path)
    assert isinstance(caught.value.__cause__, error_type)


@pytest.mark.parametrize("name,content_kind", [
    ("fake.png", "gif"), ("fake.gif", "png"),
])
def test_extension_and_real_format_must_agree(tmp_path, name, content_kind):
    content = make_gif()
    if content_kind == "png":
        with BytesIO() as buffer:
            Image.new("RGB", (24, 20), "red").save(buffer, format="PNG")
            content = buffer.getvalue()
    store = ImageStore(upload_dir=tmp_path / "uploads")
    with pytest.raises(ImageInputError):
        store.save_upload(BytesIO(content), name)
    assert list(store.upload_dir.iterdir()) == []


def test_store_upload_and_local_copy_preserve_gif(tmp_path):
    source = write_gif(tmp_path)
    store = ImageStore(upload_dir=tmp_path / "uploads")
    uploaded = store.save_upload(BytesIO(source.read_bytes()), "sample.GIF")
    copied = store.save_local_copy(source)
    for stored in (uploaded, copied):
        assert stored.format == "GIF"
        assert stored.gif_info.frame_count == 3
        assert stored.path.read_bytes() == source.read_bytes()
        assert len(stored.sha256) == 64


def test_default_frame_limit_accepts_boundary_and_rejects_next_frame(tmp_path):
    path = write_gif(tmp_path, make_gif(count=120))
    assert inspect_gif(path).frame_count == 120
    path.write_bytes(make_gif(count=121))
    with pytest.raises(ImageInputError, match="gif_frame_count_exceeded"):
        inspect_gif(path)


@pytest.mark.parametrize("format_name,extension", [
    ("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp"),
])
def test_static_images_regression(tmp_path, format_name, extension):
    with BytesIO() as buffer:
        Image.new("RGB", (32, 24), "green").save(buffer, format=format_name)
        content = buffer.getvalue()
    store = ImageStore(upload_dir=tmp_path / "uploads", min_bytes=0)
    result = store.save_upload(BytesIO(content), f"static.{extension}")
    assert result.format == format_name
    assert result.gif_info is None


def test_prepared_frames_have_order_and_distinct_nonfirst_content(tmp_path):
    path = write_gif(tmp_path, make_gif(count=8))
    content = prepare_gif_content(path)
    labels = [item["text"] for item in content if item["type"] == "text"][1:]
    media = [item["image_url"]["url"] for item in content if item["type"] == "image_url"]
    assert len(media) == 6
    assert "原始帧号=0" in labels[0]
    assert "原始帧号=7" in labels[-1]
    pixels = []
    for url in media:
        assert url.startswith("data:image/jpeg;base64,")
        with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as frame:
            pixels.append(frame.getpixel((0, 0)))
            assert max(frame.size) <= 768
    assert pixels[0] != pixels[-1]


@pytest.mark.parametrize("disposal", [1, 2, 3])
def test_pillow_disposal_and_transparency_can_be_prepared(tmp_path, disposal):
    first = Image.new("RGBA", (32, 24), (0, 0, 0, 0))
    second = first.copy()
    second.paste((255, 0, 0, 255), (4, 4, 12, 12))
    with BytesIO() as buffer:
        first.save(
            buffer, format="GIF", save_all=True, append_images=[second],
            duration=100, disposal=disposal, loop=0,
        )
        content = prepare_gif_content(write_gif(tmp_path, buffer.getvalue()))
    media = [item for item in content if item["type"] == "image_url"]
    assert len(media) == 2
    url = media[0]["image_url"]["url"]
    with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as frame:
        assert min(frame.getpixel((0, 0))) > 240
    first.close()
    second.close()


def test_real_service_sends_one_ordered_multiframe_request(tmp_path, monkeypatch):
    service = make_service(tmp_path, provider="openai")
    captured = []

    def handler(request):
        import json

        payload = json.loads(request.content)
        captured.append(payload)
        reply = service._mock_model_result([])
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(reply)}}],
        })

    real_client = httpx.Client
    monkeypatch.setattr(
        service_module.httpx, "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = service.analyze_upload(BytesIO(make_gif(count=8)), "sample.gif")
    assert len(captured) == 1
    assert captured[0]["messages"][0]["role"] == "system"
    assert captured[0]["messages"][1]["role"] == "user"
    content = captured[0]["messages"][1]["content"]
    assert sum(item["type"] == "image_url" for item in content) == 6
    assert "原始帧号=7" in content[-2]["text"]
    assert result.metadata["vision_gif_sent_frame_count"] == 6
    assert result.metadata["vision_animation_inference"] == "sampled_frames"
    assert result.low_confidence_policy.active is True
    assert result.memory_decision.allow is False


def test_mock_graph_is_explicit_and_does_not_produce_memory_hint(tmp_path):
    runner = VisionRunner(make_service(tmp_path))
    state = runner.analyze_upload(BytesIO(make_gif()), "sample.gif", user_id="u1")
    result = state["vision_result"]
    assert result.metadata["vision_animation_inference"] == "mock"
    assert result.metadata["vision_gif_sent_frame_count"] == 0
    assert result.memory.should_consider is False
    assert result.memory_decision.reason_code == "gif_transient_media"
    assert state["memory_hint"] == ""
    assert state["metadata"]["vision_gif_frame_count"] == 3
    assert "Mock 没有真实动图理解" in state["chat_context"]


def test_media_memory_is_denied_even_when_model_requests_it(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    model = service._mock_model_result([])
    model.update({
        "image_type": "food", "confidence": 0.99, "summary": "一盘食物",
        "memory": {"should_consider": True, "reason": "用户喜欢这种食物"},
    })
    monkeypatch.setattr(service, "_analyze_with_model", lambda **kwargs: model)
    result = service.analyze_upload(BytesIO(make_gif()), "food.gif")
    assert result.memory.should_consider is False
    assert result.memory_decision.allow is False
    assert result.metadata["vision_memory_decision_allow"] is False


def test_provider_rejection_never_retries_as_first_frame(tmp_path, monkeypatch):
    service = make_service(tmp_path, provider="openai")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": "multi_image_unsupported"})

    real_client = httpx.Client
    monkeypatch.setattr(
        service_module.httpx, "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(httpx.HTTPStatusError):
        service.analyze_upload(BytesIO(make_gif()), "sample.gif")
    assert len(calls) == 1


def test_policy_invalid_values_rejected():
    with pytest.raises(ValueError):
        GifPolicy(max_samples=1)
    with pytest.raises(ValueError):
        GifPolicy(max_frames=0)


@pytest.mark.parametrize("error", [
    RuntimeError("provider_does_not_support_multiple_images"),
    ImageInputError("gif_decode_failed"),
])
def test_actual_main_vision_node_does_not_swallow_gif_failure(error):
    from types import SimpleNamespace
    from unittest.mock import Mock

    failing_runner = Mock()
    failing_runner.analyze_path.side_effect = error
    # Call the real node without initializing unrelated providers or the full graph.
    owner = SimpleNamespace(
        vision_runner=failing_runner,
        _first_image_attachment=lambda attachments: attachments[0],
    )
    event = InputEvent(
        source=InputSource.MULTIMODAL, text="看图", user_id="u1",
        attachments=[InputAttachment(type="image", path="private.gif", filename="private.gif")],
    )
    with pytest.raises(type(error), match=str(error)):
        MainRunner._run_vision_graph_node(owner, {"input_event": event})
    failing_runner.analyze_path.assert_called_once()


@pytest.mark.parametrize("suffix,should_fail", [(".gif", True), (".png", False)])
def test_missing_vision_runner_gif_rejection_and_static_regression(suffix, should_fail):
    from types import SimpleNamespace

    owner = SimpleNamespace(
        vision_runner=None,
        _first_image_attachment=lambda attachments: attachments[0],
    )
    event = InputEvent(
        source=InputSource.MULTIMODAL, text="看图", user_id="u1",
        attachments=[InputAttachment(
            type="image", path=f"private{suffix}", filename=f"private{suffix}",
        )],
    )
    if should_fail:
        with pytest.raises(RuntimeError, match="gif_vision_unavailable"):
            MainRunner._run_vision_graph_node(owner, {"input_event": event})
    else:
        result = MainRunner._run_vision_graph_node(owner, {"input_event": event})
        assert result["effective_user_text"] == "看图"


def test_unvalidated_gif_is_rejected_before_retrieval_or_provider(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from aiagent.vision.image_store import StoredImage

    service = make_service(tmp_path)
    retrieve = Mock(side_effect=AssertionError("retrieval_must_not_run"))
    analyze = Mock(side_effect=AssertionError("provider_must_not_run"))
    monkeypatch.setattr(service.character_retriever, "retrieve", retrieve)
    monkeypatch.setattr(service, "_analyze_with_model", analyze)
    stored = StoredImage(
        image_id="unvalidated", path=tmp_path / "unused.gif", sha256="0" * 64,
        width=24, height=20, format="GIF",
    )
    with pytest.raises(RuntimeError, match="gif_validation_metadata_missing"):
        service.analyze_stored_image(stored)
    retrieve.assert_not_called()
    analyze.assert_not_called()
