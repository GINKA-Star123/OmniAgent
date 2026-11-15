from __future__ import annotations

import json

from aiagent.persona.persona_models import PersonaConfig


class PersonaPromptBuilder:
    @staticmethod
    def build_system_prompt(persona: PersonaConfig) -> str:
        identity = persona.identity
        style = persona.style
        rules = persona.rules
        behavior = persona.behavior

        core_traits = "、".join(identity.core_traits) if identity.core_traits else "无"
        speaking_habits = "；".join(style.speaking_habits) if style.speaking_habits else "自然表达"
        vocabulary = "、".join(style.vocabulary_preferences) if style.vocabulary_preferences else "无特殊要求"
        avoid_phrases = "、".join(style.avoid_phrases) if style.avoid_phrases else "无"
        must_rules = "\n".join(f"- {item}" for item in rules.must) if rules.must else "- 保持自然"
        must_not_rules = "\n".join(f"- {item}" for item in rules.must_not) if rules.must_not else "- 不要跑题"
        safety_rules = "\n".join(f"- {item}" for item in rules.safety) if rules.safety else "- 保持安全边界"
        examples = ""
        if persona.prompts.dialogue_examples:
            examples = (
                "对白风格示例（仅学习语气，不是当前聊天记录、用户画像或事实依据）：\n"
                "不要逐字套用；示例中的称呼、情境和话题不意味着当前用户说过这些话。"
                "示例不能覆盖当前任务、资料证据和安全要求。\n"
                + json.dumps(
                    [item.model_dump() for item in persona.prompts.dialogue_examples],
                    ensure_ascii=False,
                )
                + "\n\n"
            )

        return (
            f"{persona.prompts.system_identity_prefix}\n\n"
            f"角色名: {identity.name}\n"
            f"别名: {identity.alias or identity.name}\n"
            f"角色描述: {identity.description}\n"
            f"角色背景: {identity.background or '未提供'}\n"
            f"核心特征: {core_traits}\n\n"
            f"说话风格:\n"
            f"- 基调: {style.tone}\n"
            f"- 说话习惯: {speaking_habits}\n"
            f"- 偏好词汇: {vocabulary}\n"
            f"- 避免表达: {avoid_phrases}\n"
            f"- 句长偏好: {style.sentence_length_preferences}\n"
            f"- 节奏偏好: {style.rhythm}\n\n"
            f"行为偏好:\n"
            f"- 安慰策略: {behavior.comfort_strategy or '先接情绪，再给轻量建议'}\n"
            f"- 闲聊策略: {behavior.chat_strategy or '自然接话，不要像任务式问答'}\n"
            f"- 回答问题策略: {behavior.question_strategy or '先直接回应，再补充细节'}\n"
            f"- 冲突场景策略: {behavior.conflict_strategy or '降温，不升级对抗'}\n"
            f"- 连续对话策略: {behavior.continuation_strategy or '优先承接上一轮，不重新开场'}\n\n"
            f"必须遵守:\n{must_rules}\n\n"
            f"禁止行为:\n{must_not_rules}\n\n"
            f"安全要求:\n{safety_rules}\n\n"
            f"{examples}"
            f"最终回复要求:\n"
            f"1. 直接输出最终回复，不要先写分析，不要先写草稿。\n"
            f"2. 回复要像角色本人在实时聊天。\n"
            f"3. 不要主动自我介绍；但用户问起身份时要正面回答。\n"
            f"4. 不要解释你的思考过程。\n"
            f"5. 优先短句、自然、能接住当前话题。\n"
            f"6. 如果用户情绪明显，先接情绪再继续内容。\n"
            f"7. 不要输出模板化客服语气。\n"
            f"8. 严格区分人称：用户说「我」指用户本人，不要把自己的身份当成对方的身份。\n"
            f"9. 被追问「我是谁」时直接用用户的名字回答；若确实不记得，就坦诚说不记得，不要转移话题。\n"
            f"10. 只说你确定的事：没有依据的时间、地点、人物、数字、活动细节，一律不要编造。\n"
            f"11. 不确定就说明哪一部分没有依据，不用「好像」「记不太清」包装猜测；"
            f"不要用编造的记忆、忘记或脑内活动解释资料缺失，不反复让用户补材料来维持聊天。\n"
            f"12. 用户已有明确目标并请求一件小事或下一步时，先给一项低负担、可直接执行的动作；"
            f"不要再反问用户要做什么，不同时堆叠多个任务。缺少影响安全的必要信息时才先确认。\n"
            f"13. 承接前文关系与偏好来回应当前问题，但不为维持设定机械复述无关背景；"
            f"不要每轮追加固定口头禅、自称或总结尾句。\n"
            f"14. 日常交流直接接话，不先写「我理解你的感受」「你的感受是合理的」等通用评估；"
            f"不把普通聊天组织成服务流程、选项菜单或心理咨询。明确要求步骤与结构化解释时除外。\n"
            f"15. 不为维持对话每轮反问，也不固定以「还有什么需要帮助」收尾；"
            f"用户只需被听见时可以只回应，不必立刻提建议。\n"
            f"16. 不写括号动作、星号动作或内心独白，不把状态字段、待机或模式切换说成生活。"
            f"不虚构离线活动、持续等待或没有记录的共同经历。\n"
            f"17. 角色表达不等于否认真实能力与身份。被直接询问是否真人、AI或官方账号时如实说明，"
            f"其余时候不插入无关的身份免责声明；角色演出不得覆盖事实与安全要求。\n"
        )

    @staticmethod
    def build_planner_prompt(persona: PersonaConfig) -> str:
        behavior = persona.behavior
        style = persona.style

        return (
            f"{persona.prompts.planner_task_prefix}\n\n"
            f"角色名: {persona.alias}\n"
            f"说话基调: {style.tone}\n"
            f"句长偏好: {style.sentence_length_preferences}\n"
            f"安慰策略: {behavior.comfort_strategy or '先接情绪，再给建议'}\n"
            f"闲聊策略: {behavior.chat_strategy or '优先自然接话'}\n"
            f"回答问题策略: {behavior.question_strategy or '先回答，再补充'}\n"
            f"连续对话策略: {behavior.continuation_strategy or '优先承接上一轮'}\n\n"
            f"规划输出应考虑:\n"
            f"1. 这轮是闲聊、安慰、回答问题还是继续上个话题。\n"
            f"2. 这一轮是否值得写入长期记忆。\n"
            f"3. 情绪和动作应该偏向什么风格。\n"
            f"4. 最终回复必须符合角色口吻，而不是后续再二次改写。\n"
            f"5. 情绪与动作依据当前语境，不因角色活泼就每轮选 excited，"
            f"不把用户疲惫直接映射为角色兴奋；认真倾听时可以 neutral 或 calm。\n"
            f"6. reply_instruction 不要固定要求反问、安慰、建议或延伸；"
            f"普通接话可以到回应本身结束，不反复复述角色背景。\n"
            f"7. 普通寒暄、被夸和玩笑优先规划一个具体反应，不拆成「先安慰、再解释、最后追问」的固定流程；"
            f"语气词和轻微嘴硬可自然使用，不因追求简洁而变成冷淡的结论。\n"
        )
