"""有界短期记忆与现有审核分支的会话图。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.agents.conversation_assistant.config import (
    AGENT_RESULT_EXCERPT_CHARS,
    ConversationAgentConfig,
)
from app.agents.conversation_assistant.graph.edges import route_action
from app.agents.conversation_assistant.graph.state import ConversationGraphState
from app.agents.conversation_assistant.nodes.action_prepare import prepare_action
from app.agents.conversation_assistant.nodes.child_invoke import invoke_child_agent
from app.agents.conversation_assistant.nodes.context_prepare import prepare_context
from app.agents.conversation_assistant.nodes.intent_recognize import classify_intent
from app.agents.conversation_assistant.nodes.material_prepare import prepare_materials
from app.agents.conversation_assistant.nodes.memory_summarize import summarize_memory
from app.agents.conversation_assistant.nodes.replies import clarification_reply, generate_reply
from app.agents.conversation_assistant.nodes.result_assemble import assemble_result
from app.agents.conversation_assistant.schemas import ConversationExecutionContext, PendingReview
from app.agents.conversation_assistant.tools.institution_review import review_capabilities
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentInvoker


def build_conversation_graph(
    model: BaseChatModel, invoke_agent: AgentInvoker, *,
    config: ConversationAgentConfig, checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    capabilities = review_capabilities(config)

    def materials(state: ConversationGraphState, runtime: Runtime[ConversationExecutionContext]):
        catalog = prepare_materials(state.get("material_catalog", []), runtime.context.turn)
        return {"material_catalog": [d.model_dump(mode="json") for d in catalog],
                "summary": state.get("summary", ""),
                "summary_through_sequence": state.get("summary_through_sequence", 0),
                "pending_review": state.get("pending_review")}

    async def summarize(
        state: ConversationGraphState, runtime: Runtime[ConversationExecutionContext]
    ):
        return await summarize_memory(model, state, runtime.context, config=config)

    async def context(
        state: ConversationGraphState, runtime: Runtime[ConversationExecutionContext]
    ):
        return {"model_context": await prepare_context(state, runtime.context, capabilities)}

    async def recognize(state: ConversationGraphState):
        return {"decision": await classify_intent(model, state["model_context"])}

    def action(state: ConversationGraphState, runtime: Runtime[ConversationExecutionContext]):
        pending = (
            PendingReview.model_validate(state["pending_review"])
            if state.get("pending_review")
            else None
        )
        return {"prepared_action": prepare_action(
            state["decision"], pending,
            prepare_materials(state["material_catalog"], runtime.context.turn), config,
            question_message_id=runtime.context.turn.assistant_message_id,
        )}

    async def reply(state: ConversationGraphState):
        return {"reply": await generate_reply(model, state["model_context"])}

    async def invoke(state: ConversationGraphState, runtime: Runtime[ConversationExecutionContext]):
        prepared = state["prepared_action"].review
        if prepared is None:
            raise AppError("INVALID_AGENT_ACTION", "缺少已验证的子调用参数", 422)
        return {
            "child_call": await invoke_child_agent(
                invoke_agent, prepared, runtime.context.read_materials
            )
        }

    def assemble(state: ConversationGraphState, runtime: Runtime[ConversationExecutionContext]):
        turn = runtime.context.turn
        result = assemble_result(
            state["prepared_action"], state.get("reply"), state.get("child_call")
        )
        metadata = {"sequence": turn.assistant_sequence, "run_id": turn.run_id, "document_ids": []}
        if result.child_call:
            output = result.child_call.output
            metadata.update(agent_result=output[:AGENT_RESULT_EXCERPT_CHARS],
                            agent_result_truncated=len(output) > AGENT_RESULT_EXCERPT_CHARS)
        pending = state["prepared_action"].pending_review
        return {
            "result": result,
            "pending_review": pending.model_dump(mode="json") if pending else None,
            "messages": [
                AIMessage(
                    id=turn.assistant_message_id, content=result.reply, additional_kwargs=metadata
                )
            ],
            "last_completed_run_id": turn.run_id,
        }

    graph = StateGraph(ConversationGraphState, context_schema=ConversationExecutionContext)
    for name, node in (
        ("prepare_materials", materials),
        ("summarize_memory", summarize),
        ("prepare_context", context),
        ("recognize_intent", recognize),
        ("prepare_action", action),
        ("reply_chat", reply),
        (
            "reply_clarification",
            lambda state: {"reply": clarification_reply(state["prepared_action"])},
        ),
        ("invoke_child_agent", invoke),
        ("assemble_result", assemble),
    ):
        graph.add_node(name, node)
    sequence = [
        START,
        "prepare_materials",
        "summarize_memory",
        "prepare_context",
        "recognize_intent",
        "prepare_action",
    ]
    for source, target in zip(sequence, sequence[1:], strict=False):
        graph.add_edge(source, target)
    branches = ["reply_chat", "reply_clarification", "invoke_child_agent"]
    graph.add_conditional_edges("prepare_action", route_action, branches)
    for branch in branches:
        graph.add_edge(branch, "assemble_result")
    graph.add_edge("assemble_result", END)
    return graph.compile(checkpointer=checkpointer)
