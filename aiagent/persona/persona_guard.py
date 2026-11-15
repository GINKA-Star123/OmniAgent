from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PersonaGuardResult:
    text:str
    changed:bool
    reasons:list[str]

class PersonaGuard:
    forbidden_phrases = [
        "作为AI",
        "作为一个AI",
        "作为语言模型",
        "我是人工智能",
        "我是一个人工智能",
        "我是AI助手",
        "作为助手",
    ]

    cold_phrases = [
        "以下是",
        "综上所述",
        "需要注意的是",
        "用户您好",
        "很高兴为您服务",
    ]

    def normalize(self, text: str) -> PersonaGuardResult:
        original = text or ""
        result = original.strip()
        reasons: list[str] = []

        # 只去掉句首无关的身份套话，不改写身份事实、引用、代码和技术解释。
        # 原先全局替换会把“我是人工智能”改成“阿绫”，也会破坏正文中的“以下是”。
        boilerplate = re.match(
            r"^(?:作为一个AI|作为AI|作为语言模型|作为助手)[，,：:]\s*",
            result,
        )
        if boilerplate and result[boilerplate.end():].strip():
            result = result[boilerplate.end():]
            reasons.append(f"removed_forbidden:{boilerplate.group().rstrip('，,：: ')}")

        greeting = "用户您好，很高兴为您服务。"
        if result.startswith(greeting) and result[len(greeting):].strip():
            result = result[len(greeting):].lstrip()
            reasons.append("softened_cold_phrase:service_greeting")

        result = self._trim_repeated_prefix(result)

        return PersonaGuardResult(
            text=result.strip(),
            changed=result.strip() != original.strip(),
            reasons=reasons,
        )

    def normalize_reply(self, text: str) -> str:
        """Return the normalized reply text expected by PersonaRuntime."""
        return self.normalize(text).text

    def validate_reply(self, text: str, config=None) -> list[str]:
        """Return lightweight persona-safety issues for downstream metadata.

        `config` is accepted for compatibility with PersonaRuntime and future
        persona-specific rules. The current checks stay conservative so they do
        not block normal replies.
        """
        result = text or ""
        issues: list[str] = []

        boilerplate = re.match(r"^(?:作为一个AI|作为AI|作为语言模型|作为助手)[，,：:]", result.strip())
        if boilerplate:
            issues.append(f"forbidden_phrase:{boilerplate.group().rstrip('，,：:')}")

        if result.strip().startswith(("用户您好", "很高兴为您服务")):
            issues.append("cold_phrase:service_greeting")

        if not result.strip():
            issues.append("empty_reply")

        return issues

    def _trim_repeated_prefix(self, text: str) -> str:
        prefixes = ["阿绫觉得，", "阿绫认为，", "嗯，"]
        for prefix in prefixes:
            doubled = prefix + prefix
            while doubled in text:
                text = text.replace(doubled, prefix)
        return text
