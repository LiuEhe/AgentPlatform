import asyncio

import pytest
from conftest import turn_resources
from langgraph.checkpoint.memory import InMemorySaver

from app.agents import build_agent_registry
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentRegistry, AgentRuntime


def test_registry_injection_and_default_factory(fake_model_factory, turn_factory):
    async def handler(schema, messages):
        return {"intent": "general_chat", "action": "answer"} if schema else "你好"

    model = fake_model_factory(handler)
    registry = AgentRegistry()
    runtime = AgentRuntime(registry)
    built = build_agent_registry(
        model, registry=registry, invoke_agent=runtime.invoke, checkpointer=InMemorySaver()
    )
    assert built is registry and model.calls == []
    turn = turn_factory()
    result = asyncio.run(
        runtime.invoke("conversation_assistant", turn.model_dump(), resources=turn_resources(turn))
    )
    assert result.output.reply == "你好"
    standalone = build_agent_registry(model, checkpointer=InMemorySaver())
    assert standalone.resolve("institution_review")
    assert standalone.resolve("conversation_assistant")


def test_conversation_registration_requires_explicit_checkpointer(fake_model_factory):
    with pytest.raises(AppError) as error:
        build_agent_registry(fake_model_factory())
    assert error.value.code == "AGENT_REGISTRATION_INVALID"
