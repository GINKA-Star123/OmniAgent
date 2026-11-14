from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from aiagent.graphs.degradation import build_degraded_memory_retrieve_state
from aiagent.graphs.metadata_utils import (
    mark_stage_done,
    mark_stage_failed,
    mark_stage_skipped,
    now_perf,
)
from aiagent.memory.approved_write import ApprovedMemoryWrite, approve_plan, verify_approved
from aiagent.memory.mem0_memory import Mem0LongTermMemory, MemoryHit
from aiagent.memory.memory_intake import MemoryIntakeService
from aiagent.memory.memory_preferences import MemoryPreferenceStore
from aiagent.memory.memory_prompt import MemoryPromptBuilder
from aiagent.memory.memory_write_audit import MemoryWriteAuditLog
from aiagent.memory.memory_write_dispatcher import MemoryWriteDispatcher
from aiagent.schemas.memory import (
    MemoryRecord,
    MemoryStorePlan,
    MemoryWriteAudit,
    MemoryWriteDecision,
)
from aiagent.services.memory_policy_llm_service import MemoryPolicyLLMService
from aiagent.state.shared_state_guard import raise_if_shared_state_error

logger = logging.getLogger(__name__)

class MemoryGraphState(TypedDict,total=False):
    user_id:str
    user_name:str
    agent_id:str
    session_id:str
    turn_id:str
    user_text:str
    assistant_text:str
    retrieval_query:str
    planner_should_store_memory:bool
    memory_hits:list[MemoryHit]
    memory_prompt_context:str
    write_decision:MemoryWriteDecision
    memory_store_plan:MemoryStorePlan
    memory_pinned_records: list[MemoryRecord]
    memory_prompt_context_data:dict[str,Any]
    store_result:dict[str,Any]
    approved_write: ApprovedMemoryWrite | None
    metadata:dict[str,Any]

class MemoryRunner:
    def __init__(
            self,
            memory:Mem0LongTermMemory,
            policy_service:MemoryPolicyLLMService,
            default_agent_id:str = "yzl",
            retrieval_limit:int =6,
            intake_service: MemoryIntakeService|None = None,
            preference_store: MemoryPreferenceStore|None = None,
            prompt_builder: MemoryPromptBuilder|None = None,
            write_dispatcher: MemoryWriteDispatcher|None = None,
            audit_log: MemoryWriteAuditLog|None = None,
            async_write_enabled: bool = True,
    ) ->None:
        self.memory = memory
        self.policy_service = policy_service
        self.default_agent_id = default_agent_id
        self.retrieval_limit = retrieval_limit
        self.intake_service = intake_service or MemoryIntakeService()
        self.preference_store = preference_store or MemoryPreferenceStore()
        self.prompt_builder = prompt_builder or MemoryPromptBuilder()
        self.write_dispatcher = write_dispatcher or MemoryWriteDispatcher()
        self.audit_log = audit_log or MemoryWriteAuditLog()
        self.async_write_enabled = bool(async_write_enabled)
        self.graph = self._build_graph()
        self.prepare_graph = self._build_prepare_graph()

    def _build_graph(self):
        graph = StateGraph(MemoryGraphState)
        graph.add_node("retrieve",self._retrieve_node)
        graph.add_node("decide_write",self._decide_write_node)
        graph.add_node("guard_write",self._guard_write_node)
        graph.add_node("store",self._store_node)

        graph.add_edge(START,"retrieve")
        graph.add_edge("retrieve","decide_write")
        graph.add_edge("decide_write","guard_write")
        graph.add_conditional_edges(
            "guard_write",
            self._route_after_guard,
            {"store":"store","end":END}
        )
        graph.add_edge("store",END)
        return graph.compile()

    def _build_prepare_graph(self):
        graph = StateGraph(MemoryGraphState)
        graph.add_node("retrieve", self._retrieve_node)
        graph.add_node("decide_write", self._decide_write_node)
        graph.add_node("guard_write", self._guard_write_node)
        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "decide_write")
        graph.add_edge("decide_write", "guard_write")
        graph.add_edge("guard_write", END)
        return graph.compile()


    def retrieve_before_reply(
        self,
        user_id:str,
        user_text:str,
        retrieval_query:str = "",
        agent_id:str|None = None
    ) ->MemoryGraphState:
        started_at = now_perf()
        agent = agent_id or self.default_agent_id
        try:
            if not self.preference_store.is_enabled(user_id=user_id,agent_id=agent):
                return {
                    "user_id": user_id,
                    "agent_id": agent,
                    "memory_hits": [],
                    "memory_prompt_context": "无长期记忆。",
                    "metadata": mark_stage_skipped(
                        {},
                        "memory_retrieve",
                        "long_term_memory_disabled_by_user",
                        memory_long_term_enabled=False,
                        memory_error="",
                    ),
                }
            return self._retrieve_node(
                {
                    "user_id":user_id,
                    "user_text":user_text,
                    "retrieval_query":retrieval_query,
                    "agent_id":agent_id or self.default_agent_id
                }
            )
        except Exception as exc:
            raise_if_shared_state_error(exc)
            # 可选记忆服务允许降级，共享状态的错误则必须传播。
            return build_degraded_memory_retrieve_state(  #type:ignore
                user_id=user_id,
                agent_id=agent,
                metadata=mark_stage_failed(
                    {},
                    "memory_retrieve",
                    started_at,
                    "memory_retrieve_failed",
                    memory_error="memory_retrieve_failed",
                ),
            )

    def run_after_reply(
        self, user_id: str, user_name: str, session_id: str, turn_id: str,
        user_text: str, assistant_text: str, retrieval_query: str,
        planner_should_store_memory: bool, memory_prompt_context: str = "",
        metadata: dict[str, Any] | None = None, agent_id: str | None = None,
    ) -> MemoryGraphState:
        return self._write_after_reply(
            user_id=user_id, user_name=user_name, session_id=session_id, turn_id=turn_id,
            user_text=user_text, assistant_text=assistant_text, retrieval_query=retrieval_query,
            planner_should_store_memory=planner_should_store_memory,
            memory_prompt_context=memory_prompt_context, metadata=metadata,
            agent_id=agent_id, background=False,
        )

    def run_after_reply_async(
        self, user_id: str, user_name: str, session_id: str, turn_id: str,
        user_text: str, assistant_text: str, retrieval_query: str,
        planner_should_store_memory: bool, memory_prompt_context: str = "",
        metadata: dict[str, Any] | None = None, agent_id: str | None = None,
    ) -> MemoryGraphState:
        return self._write_after_reply(
            user_id=user_id, user_name=user_name, session_id=session_id, turn_id=turn_id,
            user_text=user_text, assistant_text=assistant_text, retrieval_query=retrieval_query,
            planner_should_store_memory=planner_should_store_memory,
            memory_prompt_context=memory_prompt_context, metadata=metadata,
            agent_id=agent_id, background=self.async_write_enabled,
        )

    def _write_after_reply(
        self, *, user_id, user_name, session_id, turn_id, user_text, assistant_text,
        retrieval_query, planner_should_store_memory, memory_prompt_context,
        metadata, agent_id, background,
    ) -> MemoryGraphState:
        started_at = now_perf()
        del user_name, metadata
        agent = agent_id or self.default_agent_id
        payload = None
        preparation_metadata = {}
        try:
            if not self.preference_store.is_enabled(user_id=user_id, agent_id=agent):
                result = {"ok": False, "status": "skipped", "reason": "memory_disabled"}
            else:
                prepared = self.prepare_graph.invoke({
                    "user_id": user_id, "agent_id": agent,
                    "session_id": session_id, "turn_id": turn_id,
                    "user_text": user_text, "assistant_text": assistant_text,
                    "retrieval_query": retrieval_query or user_text,
                    "planner_should_store_memory": planner_should_store_memory,
                    "memory_prompt_context": memory_prompt_context, "metadata": {},
                })
                preparation_metadata = dict(prepared.get("metadata") or {})
                payload = prepared.get("approved_write")
                if payload is None:
                    plan = prepared.get("memory_store_plan")
                    status = getattr(plan, "status", "blocked")
                    result = {"ok": False, "status": status, "reason": "memory_not_approved"}
                elif background:
                    # 后台参数唯一字段：签发后的不可变批准载荷。
                    result = self.write_dispatcher.submit(self._commit_approved, payload=payload)
                else:
                    result = self._commit_approved(payload=payload)
        except Exception as exc:
            raise_if_shared_state_error(exc)
            result = {"ok": False, "status": "failed", "reason": "memory_prepare_failed"}
        if payload is None or result.get("status") in {"queued", "dropped", "failed"}:
            self._audit_safe(user_id=user_id, agent_id=agent,
                             status=str(result.get("status", "failed")))
        status = str(result.get("status", "failed"))
        extra = {"memory_write_status": status, "memory_write_async": bool(background)}
        if status == "failed":
            write_metadata = mark_stage_failed(
                preparation_metadata, "memory_store", started_at, "memory_write_failed", **extra,
            )
        elif status in {"skipped", "blocked", "duplicate", "dropped"}:
            write_metadata = mark_stage_skipped(
                preparation_metadata, "memory_store", f"memory_{status}", **extra,
            )
        else:
            write_metadata = mark_stage_done(preparation_metadata, "memory_store", started_at, **extra)
        return {"user_id": user_id, "agent_id": agent, "store_result": result,
                "metadata": write_metadata}

    def _commit_approved(self, *, payload: ApprovedMemoryWrite) -> dict[str, Any]:
        try:
            verify_approved(payload)
            if not self.preference_store.is_enabled(user_id=payload.user_id, agent_id=payload.agent_id):
                result = {"ok": False, "status": "skipped", "reason": "memory_disabled"}
            else:
                result = self.memory.add_approved(payload)
                if not isinstance(result, dict) or result.get("status") not in {"stored", "skipped", "failed"}:
                    result = {"ok": False, "status": "failed", "reason": "memory_backend_result_invalid"}
                elif result.get("status") == "stored" and result.get("ok") is not True:
                    result = {"ok": False, "status": "failed", "reason": "memory_backend_result_invalid"}
        except Exception as exc:
            raise_if_shared_state_error(exc)
            result = {"ok": False, "status": "failed", "reason": "memory_backend_failed"}
        self._audit_safe(user_id=payload.user_id, agent_id=payload.agent_id,
                         status=str(result.get("status", "failed")))
        return result

    def _audit_safe(self, *, user_id: str, agent_id: str, status: str) -> None:
        allowed = {"stored", "skipped", "blocked", "duplicate", "failed", "queued", "dropped"}
        status = status if status in allowed else "failed"
        try:
            self.audit_log.append(MemoryWriteAudit(
                audit_id=uuid.uuid4().hex, user_id=user_id, agent_id=agent_id,
                status=status, reason=f"memory_{status}", memory_text="",
                source="chat_turn",
            ))
        except Exception:
            logger.warning("memory_audit_unavailable")

    def write_status(self) -> dict[str, Any]:
        status = self.write_dispatcher.status()
        status["async_enabled"] = self.async_write_enabled
        return status

    def drain_writes(self, timeout: float = 5.0) -> bool:
        return self.write_dispatcher.drain(timeout=timeout)

    def audit_records(self, *, user_id: str = "", limit: int = 20) -> dict[str, Any]:
        try:
            records = self.audit_log.tail(user_id=user_id, limit=limit)
            total = self.audit_log.count(user_id=user_id)
        except Exception:
            return {
                "enabled": True,
                "count": 0,
                "records": [],
                "reason": "audit_read_failed",
                "error": "audit_read_failed",
            }

        return {
            "enabled": True,
            "count": total,
            "records": [record.model_dump(mode="json") for record in records],
        }

    def _retrieve_node(self, state: MemoryGraphState) -> MemoryGraphState:
        started_at = now_perf()
        query = state.get("retrieval_query", "") or state.get("user_text", "")
        user_id = state["user_id"]  # type: ignore
        agent_id = state.get("agent_id") or self.default_agent_id

        try:
            hits = self.memory.search(
                query=query,
                user_id=user_id,
                agent_id=agent_id,
                limit=self.retrieval_limit,
            )
        except Exception as exc:
            raise_if_shared_state_error(exc)
            metadata = mark_stage_failed(
                state.get("metadata") or {},
                "memory_retrieve",
                started_at,
                "memory_retrieve_failed",
                memory_error="memory_retrieve_failed",
                memory_retrieval_query="",
            )
            return {
                "memory_hits": [],
                "memory_pinned_records": [],
                "memory_prompt_context": "无长期记忆。",
                "memory_prompt_context_data": {},
                "metadata": metadata,
            }

        pinned_records: list[MemoryRecord] = []
        pinned_error = ""
        try:
            pinned_records = self.memory.list_pinned_records(
                user_id=user_id,
                agent_id=agent_id,
                limit=self.prompt_builder.pinned_limit,
            )
        except Exception as exc:
            raise_if_shared_state_error(exc)
            pinned_error = "memory_pinned_retrieve_failed"
            pinned_records = []

        combined_hits = self._merge_hits(
            [
                *self._hits_from_pinned_records(pinned_records),
                *hits,
            ]
        )

        prompt_context = self.prompt_builder.build(
            hits=combined_hits,
            pinned_records=pinned_records,
        )

        metadata = mark_stage_done(
            state.get("metadata") or {},
            "memory_retrieve",
            started_at,
            memory_error="",
            memory_retrieval_query="",
            memory_hit_count=len(combined_hits),
            memory_retrieved_hit_count=len(hits),
            memory_pinned_count=len(pinned_records),
            memory_prompt_chars=prompt_context.char_count,
            memory_prompt_item_count=prompt_context.total_count,
            memory_prompt_truncated=prompt_context.truncated,
            memory_prompt_compressed=True,
            memory_prompt_layer_counts=prompt_context.layer_counts,
            memory_prompt_selected_ids=prompt_context.selected_ids,
            memory_prompt_selected_layers=prompt_context.selected_layers,
            memory_prompt_compression_reason=prompt_context.compression_reason,
            memory_pinned_error=pinned_error,
        )

        return {
            "memory_hits": combined_hits,
            "memory_pinned_records": pinned_records,
            "memory_prompt_context": prompt_context.text,
            "memory_prompt_context_data": prompt_context.model_dump(mode="json"),
            "metadata": metadata,
        }
    def _decide_write_node(self, state: MemoryGraphState) -> MemoryGraphState:
        started_at = now_perf()
        try:
            decision = self.policy_service.decide_write(
                user_text=state.get("user_text", ""),
                assistant_text=state.get("assistant_text", ""),
                existing_memory_context=state.get("memory_prompt_context", ""),
                planner_should_store_memory=bool(state.get("planner_should_store_memory")),
            )
            return {
                "write_decision": decision,
                "metadata": mark_stage_done(
                    state.get("metadata"), "memory_decide_write", started_at,
                    memory_write_should_store=decision.should_store,
                ),
            }
        except Exception as exc:
            raise_if_shared_state_error(exc)
            return {
                "write_decision": MemoryWriteDecision(),
                "metadata": mark_stage_failed(
                    state.get("metadata"), "memory_decide_write", started_at,
                    "memory_policy_failed",
                ),
            }

    def _guard_write_node(self, state: MemoryGraphState) -> MemoryGraphState:
        started_at = now_perf()
        try:
            plan = self.intake_service.build_store_plan(
                decision=state.get("write_decision"),
                memory_hits=list(state.get("memory_hits", [])),
                existing_memory_context=state.get("memory_prompt_context", ""),
                user_text=state.get("user_text", ""),
                assistant_text=state.get("assistant_text", ""),
            )
            payload = None
            if plan.should_store:
                payload = approve_plan(
                    plan, user_id=state["user_id"], ## type: ignore
                    agent_id=state.get("agent_id") or self.default_agent_id,
                    session_id=state.get("session_id", ""), turn_id=state.get("turn_id", ""),
                )
            return {"memory_store_plan": plan, "approved_write": payload,
                    "metadata": mark_stage_done(
                        state.get("metadata"), "memory_guard_write", started_at,
                        memory_store_plan_status=plan.status,
                    )}
        except Exception as exc:
            raise_if_shared_state_error(exc)
            return {"approved_write": None,
                    "memory_store_plan": MemoryStorePlan(status="blocked", reason="approval_failed"),
                    "metadata": mark_stage_failed(
                        state.get("metadata"), "memory_guard_write", started_at,
                        "memory_approval_failed",
                    )}

    def _route_after_guard(self, state: MemoryGraphState) -> str:
        return "store" if state.get("approved_write") is not None else "end"

    def _store_node(self, state: MemoryGraphState) -> MemoryGraphState:
        started_at = now_perf()
        payload = state.get("approved_write")
        plan = state.get("memory_store_plan")
        if payload is None or plan is None or not (
            plan.should_store and plan.status == "ready" and plan.guard.allowed
            and not plan.dedup.duplicate
            and plan.memory_text == plan.guard.redacted_text == payload.text
            and payload.user_id == state.get("user_id")
            and payload.agent_id == (state.get("agent_id") or self.default_agent_id)
        ):
            return {
                "store_result": {"ok": False, "status": "blocked", "reason": "approval_invalid"},
                "metadata": mark_stage_skipped(
                    state.get("metadata"), "memory_store", "approval_invalid",
                    memory_write_status="blocked",
                ),
            }
        result = self._commit_approved(payload=payload)
        status = str(result.get("status", "failed"))
        if status == "stored":
            metadata = mark_stage_done(
                state.get("metadata"), "memory_store", started_at, memory_write_status=status,
            )
        elif status == "skipped":
            metadata = mark_stage_skipped(
                state.get("metadata"), "memory_store", "memory_disabled", memory_write_status=status,
            )
        else:
            metadata = mark_stage_failed(
                state.get("metadata"), "memory_store", started_at,
                "memory_write_failed", memory_write_status="failed",
            )
        return {"store_result": result, "metadata": metadata}

    def get_user_preference(self, user_id: str, agent_id: str | None = None):
        return self.preference_store.get(
            user_id=user_id,
            agent_id=agent_id or self.default_agent_id,
        )

    def set_user_preference(
        self,
        *,
        user_id: str,
        long_term_enabled: bool,
        reason: str = "",
        agent_id: str | None = None,
    ):
        return self.preference_store.set(
            user_id=user_id,
            agent_id=agent_id or self.default_agent_id,
            long_term_enabled=long_term_enabled,
            reason=reason,
        )

    def _hits_from_pinned_records(self, records: list[MemoryRecord]) -> list[MemoryHit]:
        hits: list[MemoryHit] = []

        for record in records:
            metadata = dict(record.metadata or {})
            metadata["category"] = record.category.value
            metadata["importance"] = record.importance.value
            metadata["memory_layer"] = record.layer.value
            metadata["pinned"] = True
            if record.pinned_at:
                metadata["pinned_at"] = record.pinned_at

            hits.append(
                MemoryHit(
                    id=record.id,
                    memory=record.memory,
                    score=record.score,
                    metadata=metadata,
                    relations=record.relations,
                    pinned=True,
                    pinned_at=record.pinned_at,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )

        return hits
    def _append_audit(self, state: MemoryGraphState) -> None:
        result = state.get("store_result") or {}
        self._audit_safe(
            user_id=state.get("user_id", ""),
            agent_id=state.get("agent_id") or self.default_agent_id,
            status=str(result.get("status", "skipped")) if isinstance(result, dict) else "failed",
        )

    def _append_audit_failure(
        self, *, user_id: str, agent_id: str, session_id: str, turn_id: str, error: str,
    ) -> None:
        self._audit_safe(user_id=user_id, agent_id=agent_id, status="failed")

    def _utc_now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _merge_hits(self, hits: list[MemoryHit]) -> list[MemoryHit]:
        seen_ids: set[str] = set()
        seen_texts: set[str] = set()
        result: list[MemoryHit] = []

        for hit in hits:
            normalized = self._normalize_memory_text(hit.memory)
            if hit.id and hit.id in seen_ids:
                continue
            if normalized in seen_texts:
                continue

            if hit.id:
                seen_ids.add(hit.id)
            seen_texts.add(normalized)
            result.append(hit)

        return result

    def _normalize_memory_text(self, text: str) -> str:
        return "".join(str(text or "").strip().lower().split())
