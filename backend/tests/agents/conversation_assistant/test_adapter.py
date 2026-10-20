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
