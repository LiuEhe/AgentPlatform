import asyncio

import pytest

from app.agents.conversation_assistant.adapter import ConversationAssistantAgent
from app.agents.conversation_assistant.config import ConversationAgentConfig
from app.agents.conversation_assistant.graph.graph import build_conversation_graph
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentContext


def agent(model):
    async def child(*args):
        pytest.fail("当前输入不应调用子智能体")

    return ConversationAssistantAgent(
        build_conversation_graph(
            model,
            child,
            config=ConversationAgentConfig(False, 50000),
        )
    )


def test_chat_without_documents_uses_plain_reply(fake_model_factory, turn_factory):
    async def handler(schema, messages):
        return {"intent": "general_chat", "action": "answer"} if schema else "你好"

    model = fake_model_factory(handler)
    result = asyncio.run(
        agent(model).invoke(
            turn_factory().model_dump(),
            AgentContext("invoke1", "conversation_assistant"),
        )
    )
    assert result.reply == "你好" and result.child_call is None
    assert len(model.calls) == 2


def test_review_decision_does_not_generate_fake_output(fake_model_factory, turn_factory):
    async def handler(schema, messages):
        assert schema is not None
        return {
            "intent": "institution_review",
            "action": "call_agent",
            "target_agent_id": "institution_review",
        }

    model = fake_model_factory(handler)
    result = asyncio.run(
        agent(model).invoke(
            turn_factory().model_dump(),
            AgentContext("invoke1", "conversation_assistant"),
        )
    )
    assert result.child_call is None and result.continuation is not None
    assert "草稿" in result.reply and len(model.calls) == 1


def test_invalid_input_is_rejected(fake_model_factory):
    with pytest.raises(AppError) as raised:
        asyncio.run(
            agent(fake_model_factory()).invoke(
                {},
                AgentContext("i", "conversation_assistant"),
            )
        )
    assert raised.value.code == "INVALID_AGENT_INPUT"


def test_real_model_chunks_arrive_before_completion_without_intent_tokens(turn_factory):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langchain_core.output_parsers import JsonOutputParser

    class StreamingModel(FakeListChatModel):
        gate: object
        calls: int = 0

        def with_structured_output(self, schema, **kwargs):
            return self | JsonOutputParser(pydantic_object=schema)

        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            chat = self.i == 1
            async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
                yield chunk
                if chat and chunk.message.content == "你":
                    await self.gate.wait()

    async def scenario():
        gate, first = asyncio.Event(), asyncio.Event()
        events = []
        model = StreamingModel(
            responses=['{"intent":"general_chat","action":"answer"}', "你好"], gate=gate
        )

        def emit(event):
            events.append(event)
            if event.kind == "text_delta":
                first.set()

        task = asyncio.create_task(
            agent(model).invoke(
                turn_factory().model_dump(),
                AgentContext("stream", "conversation_assistant", on_event=emit),
            )
        )
        try:
            await asyncio.wait_for(first.wait(), timeout=2)
            assert not task.done()
            assert [e.text for e in events if e.kind == "text_delta"] == ["你"]
            gate.set()
            result = await task
            assert result.reply == "你好" and model.calls == 2
            assert "".join(e.text for e in events if e.kind == "text_delta") == "你好"
        finally:
            gate.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_review_pushes_real_stage_and_returns_only_complete_child_output(
    fake_model_factory,
    turn_factory,
):
    from app.runtime.agent_runtime import AgentExecution
    from app.schemas.conversation_turn import TurnDocument

    async def scenario():
        entered, finish = asyncio.Event(), asyncio.Event()
        events = []

        async def intent(schema, messages):
            assert schema is not None
            return {
                "intent": "institution_review",
                "action": "call_agent",
                "target_agent_id": "institution_review",
                "review_args": {
                    "draft": {"kind": "document", "id": "draft"},
                    "review_mode": "knowledge_base",
                },
            }

        async def child(agent_id, payload):
            entered.set()
            await finish.wait()
            return AgentExecution("child", agent_id, "# 完整报告\n\n审核结论")

        adapter = ConversationAssistantAgent(
            build_conversation_graph(
                fake_model_factory(intent),
                child,
                config=ConversationAgentConfig(True, 50000),
            )
        )
        turn = turn_factory(
            documents=(
                TurnDocument(
                    id="draft",
                    filename="draft.docx",
                    markdown="第一条 采购制度",
                ),
            )
        )
        task = asyncio.create_task(
            adapter.invoke(
                turn.model_dump(),
                AgentContext("review", "conversation_assistant", on_event=events.append),
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert any(e.kind == "stage" and e.text == "正在执行制度审核" for e in events)
            assert not any(e.kind == "text_delta" for e in events)
            finish.set()
            result = await task
            assert result.child_call.output == "# 完整报告\n\n审核结论"
            assert not any(e.kind == "text_delta" for e in events)
        finally:
            finish.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
