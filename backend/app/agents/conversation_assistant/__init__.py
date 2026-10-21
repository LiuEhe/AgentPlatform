"""会话助手注册入口，启动时编译业务图并注入受限子调用能力。"""

from app.agents import AgentBuildContext
from app.agents.conversation_assistant.adapter import ConversationAssistantAgent
from app.agents.conversation_assistant.config import ConversationAgentConfig
from app.agents.conversation_assistant.graph.graph import build_conversation_graph
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentRegistry


def register_agent(registry: AgentRegistry, context: AgentBuildContext) -> None:
    if context.invoke_agent is None:
        raise AppError("AGENT_REGISTRATION_INVALID", "会话调用依赖未配置", 500)
    graph = build_conversation_graph(
        context.model,
        context.invoke_agent,
        config=ConversationAgentConfig(
            knowledge_base_configured=context.conversation_knowledge_base_configured,
            max_review_chars=context.conversation_max_review_chars,
        ),
    )
    registry.register(
        "conversation_assistant",
        ConversationAssistantAgent(
            graph,
            graph_config_factory=context.graph_config_factory,
            evaluation_sink=context.evaluation_sink,
        ),
    )
