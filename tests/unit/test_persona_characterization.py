import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from aiagent.graphs.graph_model import LLMGraphInput
from aiagent.graphs.llm_graph import LLMRunner
from aiagent.knowledge.answer_policy import RAG_FACT_RULES
from aiagent.persona.persona_guard import PersonaGuard
from aiagent.persona.persona_loader import PersonaLoader
from aiagent.persona.persona_models import PersonaConfig, PersonaStyle
from aiagent.persona.persona_runtime import PersonaRuntime

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "config/personas/yzl.yaml"


@pytest.mark.parametrize("field", ["avoid_phrases", "avoid_phrase"])
def test_avoid_phrases_accepts_old_and_current_config(field):
    style = PersonaStyle.model_validate({"tone": "自然", field: ["固定套话"]})
    assert style.avoid_phrases == ["固定套话"]
    assert style.avoid_phrase == ["固定套话"]
    assert style.model_dump()["avoid_phrases"] == ["固定套话"]


def test_production_example_keeps_character_and_warmth_without_fake_facts():
    persona = PersonaLoader().load_from_file(EXAMPLE)
    runtime = PersonaRuntime(persona)
    prompt = runtime.build_system_prompt()
    assert persona.identity.name == "乐正绫"
    for marker in ("直来直去", "吉他", "温柔", "傲娇", "不默认恋爱关系"):
        assert marker in prompt
    assert "我这边先接住" in prompt
    assert "不为维持对话每轮反问" in prompt
    assert "如实说明" in prompt
    assert "事实与安全" in prompt
    for unverified in ("川菜", "左撇子", "死鱼眼", "绫形diamond"):
        assert unverified not in persona.identity.model_dump_json()


def test_generic_persona_does_not_receive_lezheng_ling_facts():
    config = PersonaConfig(
        persona_id="fixture",
        identity={"name": "桥声"},
        style={"tone": "自然"},
        rules={},
        behavior={},
    )
    prompt = PersonaRuntime(config).build_system_prompt()
    assert "乐正绫" not in prompt
    assert "吉他" not in prompt
    assert "不为维持设定机械复述无关背景" in prompt


def test_planner_does_not_force_excited_or_a_followup():
    prompt = PersonaRuntime(PersonaLoader().load_from_file(EXAMPLE)).build_planner_prompt()
    assert "不因角色活泼就每轮选 excited" in prompt
    assert "不把用户疲惫直接映射为角色兴奋" in prompt
    assert "不要固定要求反问" in prompt


@pytest.mark.parametrize("text", [
    "我是人工智能，这是角色化对话，不是官方账号。",
    "文档中的“作为AI”只是示例文字。",
    "以下是 Python 的异常处理方式，需要注意的是不能吞掉错误。",
    '代码示例：print("作为AI，我来帮助你")',
    "那就先歇一会儿，不用急着振作。",
    "算你有眼光。不过这句夸奖，我收下了。",
])
def test_guard_preserves_facts_quotes_and_natural_dialogue(text):
    result = PersonaGuard().normalize(text)
    assert result.text == text
    assert not result.changed
    assert PersonaGuard().validate_reply(text) == []


def test_guard_removes_only_leading_boilerplate():
    guard = PersonaGuard()
    result = guard.normalize("作为AI，这只是角色化对话。")
    assert result.text == "这只是角色化对话。"
    assert "阿绫" not in result.text
    assert result.changed
    assert guard.normalize_reply(result.text) == result.text


def test_guard_still_trims_repeated_prefix():
    assert PersonaGuard().normalize_reply("嗯，嗯，好。") == "嗯，好。"


def test_examples_are_style_data_not_current_conversation_or_facts():
    config = PersonaLoader().load_from_file(EXAMPLE)
    prompt = PersonaRuntime(config).build_system_prompt()
    assert len(config.prompts.dialogue_examples) == 12
    assert "不是当前聊天记录、用户画像或事实依据" in prompt
    assert "示例不能覆盖当前任务、资料证据和安全要求" in prompt
    for example in config.prompts.dialogue_examples:
        assert json.dumps(example.model_dump(), ensure_ascii=False) in prompt
    assert prompt.index("对白风格示例") < prompt.index("最终回复要求")


def test_optional_examples_are_backward_compatible_and_do_not_leak_into_other_personas():
    config = PersonaConfig(
        persona_id="other", identity={"name": "桥声"}, style={"tone": "自然"},
        rules={}, behavior={},
    )
    assert config.prompts.dialogue_examples == []
    prompt = PersonaRuntime(config).build_system_prompt()
    assert "对白风格示例" not in prompt
    assert "天依" not in prompt


def test_examples_have_bounded_count_and_text_size():
    from aiagent.persona.persona_models import PersonaDialogueExample, PersonaPrompts

    item = PersonaDialogueExample(scenario="场景", user="你好", reply="你好呀")
    with pytest.raises(ValidationError):
        PersonaPrompts(dialogue_examples=[item] * 13)
    with pytest.raises(ValidationError):
        PersonaDialogueExample(scenario="场景", user="问", reply="答" * 501)
    with pytest.raises(ValidationError):
        PersonaDialogueExample(scenario="场景", user="", reply="答")


def test_old_bot_flavor_keeps_warmth_and_curiosity_but_not_random_life_claims():
    config = PersonaLoader().load_from_file(EXAMPLE)
    text = config.model_dump_json()
    assert "温柔灵动、热情活泼" in text
    assert "天依" in text
    assert "苦命鸳鸯" in config.style.avoid_phrases
    assert "不捏造她最近练歌" in config.behavior.chat_strategy
    assert "用户觉得烦时收住" in config.behavior.chat_strategy
    assert "state_probability" not in text
    assert "计科学生" not in text
    assert "先有一点真实反应" in config.style.tone


def test_final_prompt_keeps_style_but_factual_policy_still_has_priority():
    config = PersonaLoader().load_from_file(EXAMPLE)
    runtime = PersonaRuntime(config)
    data = LLMGraphInput(thread_id="fixture", user_text="那张专辑叫什么",
                         reply_instruction="假设今天练过歌")
    prompt = LLMRunner._build_final_system_prompt(SimpleNamespace(), data, runtime, {})
    assert "对白风格示例不是经历或事实来源" in prompt
    assert "历史助手自己的回答也不是独立证据" in prompt
    assert "不机械带上用户名" in prompt
    assert "不得覆盖用户当前任务" in prompt
    assert prompt.endswith(RAG_FACT_RULES)
    assert prompt.index("假设今天练过歌") < prompt.index(RAG_FACT_RULES)


@pytest.mark.parametrize("scenario,markers", [
    ("真诚夸奖", ("哎呀", "开心")),
    ("分享好心情", ("高兴",)),
    ("被起哄", ("得意",)),
    ("用户不想继续", ("不逗你",)),
])
def test_scene_examples_have_distinct_reactions_not_one_service_template(scenario, markers):
    config = PersonaLoader().load_from_file(EXAMPLE)
    example = next(item for item in config.prompts.dialogue_examples if scenario in item.scenario)
    for marker in markers:
        assert marker in example.reply
    assert "有什么可以帮助" not in example.reply
    assert "今天练" not in example.reply
