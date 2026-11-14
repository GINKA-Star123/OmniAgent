from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from aiagent.graphs.graph_model import LLMGraphInput
from aiagent.graphs.llm_graph import LLMRunner
from aiagent.graphs.main_graph import MainRunner
from aiagent.knowledge.fact_answer import GroundedFactAnswer
from aiagent.orchestrator.dispatcher import EventDispatcher
from aiagent.orchestrator.session_manager import SessionManager
from aiagent.schemas.inputs import InputEvent, InputSource
from aiagent.services.generation_errors import GenerationUnavailableError
from aiagent.services.llm_service import LLMService


def service(mock=False):
    return LLMService(SimpleNamespace(enable_mock_llm=mock,
                                      llm_provider="mock" if mock else "openai"))


@pytest.mark.parametrize("failure", [TimeoutError("CANARY_PROVIDER_TIMEOUT"),
                                    RuntimeError("401 CANARY_PROVIDER_BODY"),
                                    RuntimeError("LLM returned empty content")])
def test_real_generation_never_returns_user_fallback(failure, caplog):
    llm = service()
    llm.invoke_messages_strict = Mock(side_effect=failure)
    with pytest.raises(GenerationUnavailableError) as error:
        llm.invoke_messages([HumanMessage(content="RAW_USER_CANARY")], "RAW_USER_CANARY")
    assert str(error.value) == "generation_unavailable"
    assert "CANARY" not in caplog.text


def test_real_success_and_mock_are_distinct():
    real = service()
    real.invoke_messages_strict = Mock(return_value="正常生成")
    assert real.invoke_messages([], "用户原文") == "正常生成"
    mock = service(True)
    mock.invoke_messages_strict = Mock(side_effect=AssertionError("must not call real provider"))
    assert mock.invoke_messages([], "离线夹具") == "离线夹具"
    mock.invoke_messages_strict.assert_not_called()


@pytest.mark.parametrize("mode", ["model", "mock", "extractive_rag_fact"])
def test_node_keeps_model_mock_and_extractive_metadata(mode):
    llm = service(mode != "model")
    llm.invoke_messages_strict = Mock(return_value="真实回答")
    fact = GroundedFactAnswer(answer="9月17日。（来源：测试资料）", chunk_ids=("c1",))
    data = LLMGraphInput(thread_id="t", user_text="问题", retrieved_context=["证据"],
                         grounded_fact=fact if mode == "extractive_rag_fact" else None)
    stub = SimpleNamespace(llm_service=llm, _state_input=lambda _: data)
    result = LLMRunner._call_llm_node(stub, {"prompt_messages": [], "metadata": {}})
    assert result["metadata"]["llm_answer_mode"] == mode
    assert len(result["messages"]) == 1 and isinstance(result["messages"][0], AIMessage)
    if mode == "extractive_rag_fact":
        assert result["raw_reply_text"] == fact.answer
        assert result["metadata"]["llm_inference"] == "skipped_extractive"
        llm.invoke_messages_strict.assert_not_called()
    if mode == "mock":
        assert result["metadata"]["llm_mock"] == "true"


def test_failed_graph_does_not_checkpoint_fake_assistant_message():
    llm = service(True)
    runner = LLMRunner(llm)
    persona = Mock()
    persona.build_system_prompt.return_value = "测试角色"
    persona.validate_reply.return_value = []
    runner._persona_runtime_cache["failure-thread"] = persona
    llm.settings.enable_mock_llm = False
    llm.settings.llm_provider = "openai"
    llm.invoke_messages_strict = Mock(side_effect=TimeoutError("CANARY_PROVIDER_BODY"))
    data = LLMGraphInput(thread_id="failure-thread", user_text="用户输入")
    with pytest.raises(GenerationUnavailableError):
        runner.graph.invoke({"input": data.model_dump(mode="json"),
                             "messages": [HumanMessage(content="用户输入")]},
                            config={"configurable": {"thread_id": "failure-thread"}})
    snapshot = runner.graph.get_state({"configurable": {"thread_id": "failure-thread"}})
    assert not any(isinstance(message, AIMessage) for message in snapshot.values.get("messages", []))
    persona.normalize_reply.assert_not_called()


def test_full_main_graph_failure_never_broadcasts_or_writes_success_history():
    memory, llm, state_runner, planner, rag = Mock(), Mock(), Mock(), Mock(), Mock()
    memory.retrieve_before_reply.return_value = {"memory_hits": [], "memory_prompt_context": "无长期记忆。", "metadata": {}}
    state_runner.run.return_value = SimpleNamespace(emotion="neutral", intent="chat", topic="测试")
    planner.run.return_value = SimpleNamespace(retrieval_query="", should_retrieve=False,
                                               should_store_memory=True)
    rag.run.return_value = SimpleNamespace(context=[], grounded_fact=None, metadata={},
                                           query="", should_inject=False)
    llm.run.side_effect = GenerationUnavailableError()
    main = MainRunner(state_runner, planner, rag, llm, memory)
    bus, scheduler, personas, broadcaster = Mock(), Mock(), Mock(), Mock()
    scheduler.should_process_now.return_value = True
    personas.get_active_persona.return_value = SimpleNamespace(persona_id="yzl", name="测试", alias="测试")
    dialogue, interrupt, conversation = Mock(), Mock(), Mock()
    dialogue.should_accept.return_value = (True, "")
    interrupt.consume_interrupt.return_value = ""
    agent_core = SimpleNamespace(main_runner=main, _build_history_lines=lambda **kwargs: [])
    dispatcher = EventDispatcher(
        event_bus=bus, scheduler=scheduler, session_manager=SessionManager(),
        agent_core=agent_core, persona_manager=personas, output_broadcaster=broadcaster,
        agent_state=SimpleNamespace(), conversation_state=conversation,
        dialogue_manager=dialogue, interrupt_manager=interrupt,
    )
    with pytest.raises(GenerationUnavailableError):
        dispatcher.handle_input(InputEvent(source=InputSource.CHAT, user_id="u1", text="你好"))
    memory.run_after_reply.assert_not_called()
    memory.run_after_reply_async.assert_not_called()
    broadcaster.broadcast.assert_not_called()
    conversation.add_output.assert_not_called()
    dialogue.record_turn.assert_not_called()
    conversation.add_input.assert_called_once()  # 输入记录允许存在，不冒充回滚。


def test_session_scope_separates_identical_client_session_ids():
    manager = SessionManager()
    def event(user, session):
        return InputEvent(source=InputSource.CHAT, user_id=user, session_id=session)
    assert manager.resolve_session_id(event("u1", "same")) == manager.resolve_session_id(event("u1", "same"))
    assert manager.resolve_session_id(event("u1", "same")) != manager.resolve_session_id(event("u2", "same"))
    assert manager.resolve_session_id(event("u1", "one")) != manager.resolve_session_id(event("u1", "two"))
