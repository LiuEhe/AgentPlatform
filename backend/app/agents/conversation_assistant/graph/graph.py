"""构建完整单轮会话图：材料、上下文、意图、门控、回复或子调用。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.conversation_assistant.config import ConversationAgentConfig
from app.agents.conversation_assistant.graph.edges import route_action
from app.agents.conversation_assistant.graph.state import ConversationGraphState
from app.agents.conversation_assistant.nodes.action_prepare import prepare_action
from app.agents.conversation_assistant.nodes.child_invoke import invoke_child_agent
from app.agents.conversation_assistant.nodes.context_prepare import prepare_context
from app.agents.conversation_assistant.nodes.intent_recognize import classify_intent
from app.agents.conversation_assistant.nodes.material_prepare import prepare_materials
from app.agents.conversation_assistant.nodes.replies import clarification_reply, generate_reply
from app.agents.conversation_assistant.nodes.result_assemble import assemble_result
from app.agents.conversation_assistant.tools.institution_review import review_capabilities
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentInvoker


def build_conversation_graph(
    model: BaseChatModel,
    invoke_agent: AgentInvoker,
    *,
    config: ConversationAgentConfig,
) -> CompiledStateGraph:
    capabilities = review_capabilities(config)

    async def recognize(state: ConversationGraphState):
        return {"decision": await classify_intent(model, state["model_context"])}

    async def reply(state: ConversationGraphState):
        return {"reply": await generate_reply(model, state["model_context"])}

    async def invoke(state: ConversationGraphState):
        prepared = state["prepared_action"].review
        if prepared is None:
            raise AppError("INVALID_AGENT_ACTION", "缺少已验证的子调用参数", 422)
        return {"child_call": await invoke_child_agent(invoke_agent, prepared)}

    graph = StateGraph(ConversationGraphState)
    graph.add_node(
        "prepare_materials",
        lambda state: {
            "materials": prepare_materials(state["turn"]),
        },
    )
    graph.add_node(
        "prepare_context",
        lambda state: {
            "model_context": prepare_context(state["turn"], capabilities),
        },
    )
    graph.add_node("recognize_intent", recognize)
    graph.add_node(
        "prepare_action",
        lambda state: {
            "prepared_action": prepare_action(
                state["turn"],
                state["decision"],
                state["materials"],
                config,
            )
        },
    )
    graph.add_node("reply_chat", reply)
    graph.add_node(
        "reply_clarification",
        lambda state: {
            "reply": clarification_reply(state["prepared_action"]),
        },
    )
    graph.add_node("invoke_child_agent", invoke)
    graph.add_node(
        "assemble_result",
        lambda state: {
            "result": assemble_result(
                state["prepared_action"],
                state.get("reply"),
                state.get("child_call"),
            )
        },
    )
    sequence = [START, "prepare_materials", "prepare_context", "recognize_intent", "prepare_action"]
    for source, target in zip(sequence, sequence[1:], strict=False):
        graph.add_edge(source, target)
    branches = ["reply_chat", "reply_clarification", "invoke_child_agent"]
    graph.add_conditional_edges("prepare_action", route_action, branches)
    for branch in branches:
        graph.add_edge(branch, "assemble_result")
    graph.add_edge("assemble_result", END)
    return graph.compile()
