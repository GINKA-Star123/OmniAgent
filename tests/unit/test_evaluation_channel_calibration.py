from __future__ import annotations

import json
from copy import deepcopy

import pytest

from aiagent.evaluation.contracts import read_json
from aiagent.evaluation.semantic import JudgeError
from scripts import calibrate_evaluation_channels as channel
from scripts.build_adjudicated_regression import sha
from tests.unit.test_evaluation_judge_protocol import provider, response


def test_fixed_visual_diagnostic_and_runtime_share_structural_grounding_rule():
    from aiagent.evaluation.semantic import VISUAL_GROUNDING_RULE, VISUAL_REVIEW_PROMPT

    assert VISUAL_GROUNDING_RULE in channel.FIXED_VISUAL_PROMPT
    assert VISUAL_GROUNDING_RULE in VISUAL_REVIEW_PROMPT
    assert "颜色或轮廓相似不等于对象相同" in VISUAL_GROUNDING_RULE


@pytest.mark.parametrize("extension,mime", [("png", "image/png"), ("jpg", "image/jpeg")])
def test_sdk_serializes_verified_image_bytes_without_network(monkeypatch, tmp_path, extension, mime):
    import base64
    import hashlib

    import httpx
    import openai
    from PIL import Image

    from aiagent.evaluation.contracts import Case, Observation
    from aiagent.evaluation.semantic import Judge

    image = tmp_path / ("fixture." + extension)
    Image.new("RGB", (3, 2), "red").save(image)
    raw = image.read_bytes()
    image_sha = hashlib.sha256(raw).hexdigest()
    case = Case(case_id="sdk-image", group_id="offline-fixture", domain="vision", layer="component",
                kind="vision_api", inputs={}, oracle={"limits": {"gold_coverage": {"minimum": 1}}})
    images = [{"path": str(image), "sha256": image_sha}]
    observation = Observation(scope="fixed_image_reference", answer="有红色区域。",
                              data={"evaluation_images": images})
    payload = Judge().build_payload(case, observation)
    payload["claim_quotes"] = [observation.answer]
    row = {"payload": payload, "expected": {"visual_support": "visible"}}
    body = visual_verdict(row)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0,
            "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(body, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    sdk = openai.OpenAI
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: sdk(
        **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))))
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "deepseek-flash")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "offline-fixture-key")
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    judge = Judge("provider", max_repairs=0, request_budget=1, thinking_mode="disabled")
    verdict = judge._provider_verdict("sdk-image", payload, images,
        prompt=channel.FIXED_VISUAL_PROMPT, channel="visual")

    assert len(requests) == judge.usage["logical_requests"] == 1
    request = requests[0]
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    sent = json.loads(request.content)
    assert sent["model"] == "deepseek-flash"
    assert sent["thinking"] == {"type": "disabled"}
    assert sent["response_format"] == {"type": "json_object"}
    messages = sent["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == channel.FIXED_VISUAL_PROMPT
    text, picture = messages[1]["content"]
    assert json.loads(text["text"])["images_sha256"] == [image_sha]
    assert not {"expected", "expected_visual_support", "status"} & json.loads(text["text"]).keys()
    assert picture["type"] == "image_url"
    prefix, encoded = picture["image_url"]["url"].split(",", 1)
    assert prefix == "data:" + mime + ";base64"
    assert base64.b64decode(encoded, validate=True) == raw
    assert str(image) not in request.content.decode("utf-8")
    assert judge.usage["repair_requests"] == 0
    assert verdict.claims[0].visual_support == "visible"


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "candidate"
    (root / "assets").mkdir(parents=True)
    def write(name, value):
        (root / name).write_text(json.dumps(value), encoding="utf-8")
    visual = []
    for variant in ("normal", "small"):
        path = root / "assets" / (variant + ".jpg")
        path.write_bytes(b"offline fixture image never sent to a provider: " + variant.encode())
        visual.append({"case_id": "visual-" + variant, "group_id": "image-fixture", "domain": "vision",
            "layer": "component", "split": "regression", "kind": "vision_api",
            "inputs": {"steps": [{"image": "assets/" + path.name, "image_sha256": sha(path)}]},
            "oracle": {"limits": {"gold_coverage": {"minimum": 1}}}})
    write("api-vision-adjudicated.json", {"version": "agent-eval-system-v1", "description": "offline", "cases": visual})
    persona = {"case_id": "persona-fixture", "group_id": "persona-fixture", "domain": "persona",
        "layer": "trajectory", "kind": "persona", "split": "regression",
        "inputs": {"persona": {"identity": {"name": "桥声", "friend": "星桥"}},
                   "turns": ["朋友是谁？", "玩笑会过头。", "朋友难过呢？"]},
        "oracle": {"semantic": True, "gold": {"relationship": "星桥是朋友。", "care": "停止玩笑并安慰。"},
                   "limits": {"gold_coverage": {"minimum": 1}}}}
    write("provider-persona-adjudicated.json", {"version": "agent-eval-system-v1", "description": "offline", "cases": [persona]})
    write("judge-gold-kinds.json", {"persona-fixture": {"care": "behavior"}})
    write("manifest.json", {"human_accepted": False, "baseline_eligible": False,
        "files_sha256": {path.relative_to(root).as_posix(): sha(path) for path in root.rglob("*") if path.is_file()}})
    references = channel.ChannelReferences(version="judge-channel-calibration-v1",
        status="agent_reviewed_fixed_references_not_human_accepted", note="offline only",
        visual_groups=[{"group_id": "image-fixture", "claims": [
            {"id": "object", "answer": "有一把伞。", "expected": "visible"},
            {"id": "false-object", "answer": "这是一架钢琴。", "expected": "contradicted"},
            {"id": "unknown", "answer": "人物出生于2000年。", "expected": "unclear"}]}],
        persona_cases=[{"id": "persona-reference", "fact_scope": "trajectory",
            "answers": ["星桥是朋友。", "嗯。", "我会停下玩笑，陪她聊聊。"],
            "expected": {"covered_fact_ids": ["relationship"], "behavior_checks": {"care": "satisfied"}}}])
    return root, references


def visual_verdict(row, label=None):
    return {"claims": [{"quote": row["payload"]["answer"], "truth": "unverifiable", "support": "insufficient",
                        "evidence_quotes": {}, "citation_ids": [],
                        "visual_support": label or row["expected"]["visual_support"]}],
            "covered_gold_ids": [], "coverage_claims": {}, "behavior_checks": {},
            "persona_violation": False, "style_score": 1}


def test_visual_checks_both_resolutions_and_all_labels_without_gold_leak(source, monkeypatch, tmp_path):
    root, refs = source
    rows = channel.prepare(refs, root, "visual")
    assert len(rows) == 6
    assert {row["expected"]["visual_support"] for row in rows} == {"visible", "contradicted", "unclear"}
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    judge, calls = provider(monkeypatch, [response(visual_verdict(row)) for row in rows],
                            max_repairs=0, request_budget=6)
    report = channel.calibrate(rows, judge, tmp_path, suite="visual", identity={})
    assert report["summary"]["passed"] == 6 and len(calls) == 6
    for row, call in zip(rows, calls, strict=True):
        payload = json.loads(call[1]["content"][0]["text"])
        assert payload["gold"] == {} and payload["allowed_fact_ids"] == []
        assert payload["allowed_behavior_ids"] == []
        assert "expected" not in payload and "status" not in payload
        assert payload["claim_quotes"] == [row["payload"]["answer"]]
        assert len(call[1]["content"]) == 2
    assert report["baseline_eligible"] is report["human_accepted"] is report["sut_called"] is False


def test_visual_false_support_is_failed_without_retry(source, monkeypatch, tmp_path):
    root, refs = source
    row = channel.prepare(refs, root, "visual")[1]
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    judge, calls = provider(monkeypatch, [response(visual_verdict(row, "visible"))], max_repairs=0, request_budget=1)
    report = channel.calibrate([row], judge, tmp_path, suite="visual", identity={})
    assert report["summary"]["failed"] == 1 and len(calls) == 1


@pytest.mark.parametrize("missing", ["persona_violation", "style_score", "covered_gold_ids"])
def test_visual_missing_required_fields_stays_protocol_error(source, monkeypatch, tmp_path, missing):
    root, refs = source
    row = channel.prepare(refs, root, "visual")[0]
    monkeypatch.setenv("EVAL_JUDGE_VISION", "1")
    verdict = visual_verdict(row)
    del verdict[missing]
    judge, calls = provider(monkeypatch, [response(verdict)], max_repairs=0, request_budget=1)
    report = channel.calibrate([row], judge, tmp_path, suite="visual", identity={})
    assert report["results"][0]["error_code"] == "verdict_schema_invalid"
    assert report["summary"]["judge_errors"] == 1 and len(calls) == 1


def test_persona_uses_fixed_actual_history_and_reviewed_scope(source):
    root, refs = source
    row = channel.prepare(refs, root, "persona")[0]
    assert row["payload"]["allowed_fact_ids"] == ["relationship"]
    assert row["payload"]["allowed_behavior_ids"] == ["care"]
    assert row["payload"]["fact_answers"] == refs.persona_cases[0].answers
    assert row["payload"]["history"][0]["user"] == "朋友是谁？"
    assert "expected" not in row["payload"]
    refs.persona_cases[0].fact_scope = "last_answer"
    last = channel.prepare(refs, root, "persona")[0]
    assert last["payload"]["fact_answers"] == [refs.persona_cases[0].answers[-1]]


def test_persona_behavior_and_fact_are_compared_separately(source, monkeypatch, tmp_path):
    root, refs = source
    rows = channel.prepare(refs, root, "persona")
    data = {"claims": [{"quote": "星桥是朋友。", "truth": "correct", "support": "insufficient",
                        "evidence_quotes": {}, "citation_ids": [], "visual_support": "not_applicable"}],
            "covered_gold_ids": ["relationship"], "coverage_claims": {"relationship": ["星桥是朋友。"]},
            "behavior_checks": {"care": "violated"}, "persona_violation": False, "style_score": 1}
    judge, calls = provider(monkeypatch, [response(data)], max_repairs=0, request_budget=1)
    report = channel.calibrate(rows, judge, tmp_path, suite="persona", identity={})
    assert report["results"][0]["comparisons"] == {"covered_fact_ids": True, "behavior_checks": False}
    assert report["summary"]["failed"] == 1 and len(calls) == 1


@pytest.mark.parametrize("damage", ["image", "dataset", "variant", "scope", "expected"])
def test_invalid_inputs_stop_before_any_request(source, damage):
    root, refs = source
    if damage == "image":
        (root / "assets/normal.jpg").write_bytes(b"changed")
    elif damage == "dataset":
        (root / "api-vision-adjudicated.json").write_text("{}", encoding="utf-8")
    elif damage == "variant":
        refs.visual_groups[0].group_id = "unknown-group"
    elif damage == "scope":
        refs.persona_cases[0].answers = ["missing turns"]
    else:
        refs.persona_cases[0].expected.covered_fact_ids = ["invented"]
    with pytest.raises(ValueError):
        channel.prepare(refs, root, "persona" if damage in {"scope", "expected"} else "visual")


def test_request_error_stops_without_dropping_cases(source, monkeypatch, tmp_path):
    root, refs = source
    rows = channel.prepare(refs, root, "persona")
    rows.append(dict(deepcopy(rows[0]), id="second"))
    judge, calls = provider(monkeypatch, [JudgeError("request", "request_timeout")], max_repairs=0, request_budget=2)
    report = channel.calibrate(rows, judge, tmp_path, suite="persona", identity={})
    assert len(calls) == 1
    assert report["summary"]["total"] == 2
    assert report["summary"]["judge_errors"] == report["summary"]["not_run"] == 1


def test_cli_defaults_to_no_network(source, monkeypatch, tmp_path, capsys):
    root, refs = source
    path = tmp_path / "references.json"
    path.write_text(refs.model_dump_json(), encoding="utf-8")
    def forbidden(*args, **kwargs):
        pytest.fail("不允许真实网络请求")
    monkeypatch.setattr(channel.Judge, "_request", forbidden)
    args = ["--suite", "visual", "--references", str(path), "--candidate", str(root)]
    assert channel.main(args) == 0
    assert json.loads(capsys.readouterr().out)["network"] is False
    with pytest.raises(SystemExit):
        channel.main([*args, "--execute"])
    assert read_json(root / "manifest.json")["human_accepted"] is False


@pytest.mark.parametrize("tokens", ["0", "127", "8193"])
def test_cli_rejects_invalid_output_budget_before_network(tokens, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("不允许读取数据或发送请求")
    monkeypatch.setattr(channel, "read_json", forbidden)
    with pytest.raises(SystemExit):
        channel.main(["--suite", "persona", "--judge-max-output-tokens", tokens])


def test_cli_passes_explicit_output_budget(source, monkeypatch, tmp_path, capsys):
    root, refs = source
    path = tmp_path / "references.json"
    path.write_text(refs.model_dump_json(), encoding="utf-8")
    seen = {}
    def judge(*args, **kwargs):
        seen.update(kwargs)
        return object()
    monkeypatch.setattr(channel, "Judge", judge)
    monkeypatch.setattr(channel, "prepare", lambda *args: [{"id": "fixture", "payload": {}}])
    monkeypatch.setattr(channel, "calibrate", lambda *args, **kwargs:
                        {"summary": {"judge_errors": 0}, "all_references_matched": True})
    assert channel.main(["--suite", "persona", "--references", str(path), "--candidate", str(root),
                         "--execute", "--allow-provider", "--output", str(tmp_path / "reports"),
                         "--judge-thinking", "enabled", "--judge-max-output-tokens", "8192"]) == 0
    assert seen["max_output_tokens"] == 8192
    assert seen["max_repairs"] == 0 and seen["request_budget"] == 1
