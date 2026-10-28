from __future__ import annotations

import re
from datetime import date
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict

from aiagent.knowledge.character_aliases import CHARACTER_ALIASES
from aiagent.knowledge.query_normalizer import ALIASES, has_birthday_field


class GroundedFactAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str
    chunk_ids: tuple[str, ...]


_QUESTION = re.compile(
    r"^(?:请问\s*)?(?P<subject>[^\s？?。！，,；;]{2,80}?)(?:的)?生日(?:是|在)?"
    r"(?:几月几日|几月几号|几月多少号|哪一天|哪天|什么时候|何时)"
)
_CONSTRAINTS = [
    r"(?:请|并|且)?(?:依据|根据|按照)(?:资料|知识库|检索资料)(?:简短|简洁)?(?:作答|回答)",
    r"(?:请|并|且)?(?:简短|简洁)(?:作答|回答)",
    r"(?:请|并|且)?(?:标注|注明|给出)(?:资料)?(?:来源|出处)",
    r"不同(?:声库)?版本(?:不要|别|不能)混在一起",
    r"(?:不要|别|勿)混淆(?:不同)?(?:声库)?版本",
]
_FIELD = re.compile(
    r"\s*(?:[-*]\s+)?(?:\*\*)?生日(?:\*\*)?\s*[:：]\s*(?:\*\*)?"
    r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*(?:日|号)(?:\*\*)?\s*[。.]?\s*"
)


def extract_birthday_answer(question: str, chunks: list[dict[str, Any]]) -> GroundedFactAnswer | None:
    """Answer only a narrow date lookup from unambiguous, actually injected evidence."""
    match = _QUESTION.match(question.strip())
    if match is None:
        return None
    tail = question.strip()[match.end():]
    clauses = [part.strip() for part in re.split(r"[？?。！，,；;\n]+", tail) if part.strip()]
    if any(not any(re.fullmatch(pattern, clause) for pattern in _CONSTRAINTS) for clause in clauses):
        return None

    subject = match["subject"].casefold()
    matched = []
    for chunk in chunks:
        source = str(chunk.get("source_path", "")).replace("\\", "/")
        stem = PurePosixPath(source).stem
        names = {stem, *CHARACTER_ALIASES.get(stem, ())}
        names.update(alias for alias, canonical in ALIASES.items() if canonical == stem)
        if subject in {name.casefold() for name in names}:
            matched.append(chunk)
    sources = {str(chunk.get("source_path", "")).replace("\\", "/") for chunk in matched}
    if len(sources) != 1:
        return None
    source_name = PurePosixPath(next(iter(sources))).name
    if not source_name or any(ord(char) < 32 or char in '<>[]《》' for char in source_name):
        return None

    values: set[tuple[int, int]] = set()
    ids = []
    for chunk in matched:
        for line in str(chunk.get("content", "")).splitlines():
            if not has_birthday_field(line):
                continue
            field = _FIELD.fullmatch(line)
            if field is None:
                return None
            month, day = int(field["month"]), int(field["day"])
            try:
                date(2000, month, day)
            except ValueError:
                return None
            chunk_id = str(chunk.get("chunk_id", "")).strip()
            if not chunk_id:
                return None
            values.add((month, day))
            ids.append(chunk_id)
    if len(values) != 1:
        return None
    month, day = next(iter(values))
    return GroundedFactAnswer(answer=f"{month}月{day}日。（来源：《{source_name}》）", chunk_ids=tuple(dict.fromkeys(ids)))
