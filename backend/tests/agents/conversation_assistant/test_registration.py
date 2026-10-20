import asyncio

from app.agents import build_agent_registry
from app.runtime.agent_runtime import AgentRegistry, AgentRuntime


def test_registry_injection_and_default_factory(fake_model_factory, turn_factory):
    async def handler(schema, messages):
        return {"intent": "general_chat", "action": "answer"} if schema else "你好"

    model = fake_model_factory(handler)
    registry = AgentRegistry()
    runtime = AgentRuntime(registry)
    built = build_agent_registry(model, registry=registry, invoke_agent=runtime.invoke)
    assert built is registry and model.calls == []
    result = asyncio.run(runtime.invoke("conversation_assistant", turn_factory().model_dump()))
    assert result.output.reply == "你好"
    standalone = build_agent_registry(model)
    assert standalone.resolve("institution_review")
    assert standalone.resolve("conversation_assistant")
