from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field


class PersonaIdentity(BaseModel):
    name:str
    alias:str = ""
    description:str = ""
    background: str = ""
    core_traits: list[str] = Field(default_factory=list)

class PersonaStyle(BaseModel):
    tone:str
    speaking_habits:list[str] = Field(default_factory=list)
    vocabulary_preferences:list[str] = Field(default_factory=list)
    avoid_phrases: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("avoid_phrases", "avoid_phrase"),
    )
    sentence_length_preferences: str = ""
    rhythm:str = "natural"

    @property
    def avoid_phrase(self) -> list[str]:
        """兼容旧调用方；配置输出统一使用复数形式。"""
        return self.avoid_phrases

class PersonaRules(BaseModel):
    must: list[str] = Field(default_factory=list)
    must_not : list[str] = Field(default_factory=list)
    safety:list[str] = Field(default_factory=list)

class PersonaBehavior(BaseModel):
    comfort_strategy : str =""
    chat_strategy : str = ""
    question_strategy : str = ""
    conflict_strategy : str = ""
    continuation_strategy : str = ""

class PersonaExpression(BaseModel):
    default_emotion: str ="neutral"
    emotion_bias:dict[str,str] = Field(default_factory=dict)
    motion_bias:dict[str,str] = Field(default_factory=dict)
    default_motion: str = "idle"
    default_expression: str = "neutral"

class PersonaVoice(BaseModel):
    provider: str = "indextts2"
    ref_audio_path : str = ""
    emo_alpha:float = 0.6
    use_emo_text:bool = True

class PersonaDialogueExample(BaseModel):
    scenario: str = Field(min_length=1, max_length=120)
    user: str = Field(min_length=1, max_length=300)
    reply: str = Field(min_length=1, max_length=500)

class PersonaPrompts(BaseModel):
    system_identity_prefix:str = "你就是如下角色"
    planner_task_prefix:str = "请先决定这一轮应该如何回应，再给出回复约束。"
    dialogue_examples: list[PersonaDialogueExample] = Field(default_factory=list, max_length=12)

class PersonaConfig(BaseModel):
    persona_id :str
    version: str = "1.0.0"
    identity: PersonaIdentity
    style: PersonaStyle
    rules: PersonaRules
    behavior: PersonaBehavior
    expression: PersonaExpression = Field(default_factory=PersonaExpression)
    voice: PersonaVoice = Field(default_factory=PersonaVoice)
    prompts: PersonaPrompts = Field(default_factory=PersonaPrompts)

    @property
    def name(self) -> str:
        return self.identity.name

    @property
    def alias(self) -> str:
        return self.identity.alias
