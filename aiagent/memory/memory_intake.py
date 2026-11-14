from __future__ import annotations

from datetime import UTC, datetime

from aiagent.memory.mem0_memory import MemoryHit
from aiagent.memory.memory_deduper import MemoryDeduper
from aiagent.memory.memory_safety import MemorySafetyFilter
from aiagent.schemas.memory import MemoryStorePlan, MemoryWriteDecision


class MemoryIntakeService:
    def __init__(self, safety_filter=None, deduper=None) -> None:
        self.safety_filter = safety_filter or MemorySafetyFilter()
        self.deduper = deduper or MemoryDeduper()

    def build_store_plan(
        self, *, decision: MemoryWriteDecision | None,
        memory_hits: list[MemoryHit], existing_memory_context: str,
        user_text: str, assistant_text: str, source: str = "chat_turn",
    ) -> MemoryStorePlan:
        del user_text, assistant_text
        common = {"source": source, "created_at": datetime.now(UTC).isoformat()}
        if decision is None or not decision.should_store:
            return MemoryStorePlan(reason="policy_not_approved", **common) ## type: ignore
        common.update(category=decision.category, importance=decision.importance)
        candidate = self._select_candidate(decision)
        if not candidate or len(candidate) > 2000:
            return MemoryStorePlan(reason="candidate_size_invalid", **common) ## type: ignore
        guard = self.safety_filter.evaluate(candidate)
        if not guard.allowed:
            return MemoryStorePlan(status="blocked", reason="sensitive_memory_blocked",
                                   guard=guard, **common) ## type: ignore
        dedup = self.deduper.check(
            candidate=guard.redacted_text, hits=memory_hits,
            existing_context=existing_memory_context,
        )
        if dedup.duplicate:
            return MemoryStorePlan(status="duplicate", reason="duplicate_memory",
                                   guard=guard, dedup=dedup, **common) ## type: ignore
        return MemoryStorePlan(
            should_store=True, status="ready", reason="approved_candidate",
            memory_text=guard.redacted_text, guard=guard, dedup=dedup, **common, ## type: ignore
        )

    def _select_candidate(self, decision: MemoryWriteDecision) -> str:
        facts = [item.strip() for item in decision.facts if item.strip()]
        return ";".join(facts) if facts else decision.memory_hint.strip()
