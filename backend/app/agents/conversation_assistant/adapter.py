"""会话 Agent 的边界适配：校验本轮输入，执行图并返回完整结果。"""

from collections.abc import Mapping

from langgraph.graph.state import CompiledStateGraph

from app.agents.conversation_assistant.evaluation import project_evaluation
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentContext, AgentEvent
from app.schemas.conversation_turn import ConversationTurnInput, ConversationTurnResult


class ConversationAssistantAgent:
    def __init__(
        self, graph: CompiledStateGraph, *, graph_config_factory=None, evaluation_sink=None
    ):
        self._graph = graph
        self._graph_config_factory = graph_config_factory
        self._evaluation_sink = evaluation_sink

    async def invoke(
        self,
        payload: Mapping[str, object],
        context: AgentContext,
    ) -> ConversationTurnResult:
        try:
            turn = ConversationTurnInput.model_validate(payload)
        except ValueError as exc:
            raise AppError("INVALID_AGENT_INPUT", "会话输入无效", 422) from exc
        config = self._graph_config_factory(context) if self._graph_config_factory else None
        state = {}
        async for part in self._graph.astream(
            {"turn": turn},
            config=config,
            stream_mode=["messages", "values", "updates"],
            version="v2",
        ):
            if part["type"] == "values":
                state = part["data"]
            elif part["type"] == "messages" and context.on_event:
                chunk, metadata = part["data"]
                # 只公开普通回答，结构化意图与子审核的模型输出均留在 Agent 内。
                if metadata.get("langgraph_node") == "reply_chat" and chunk.text:
                    context.on_event(AgentEvent("text_delta", chunk.text))
            elif part["type"] == "updates" and context.on_event:
                updates = part["data"]
                if "prepare_context" in updates:
                    context.on_event(AgentEvent("stage", "正在理解你的问题"))
                if "prepare_action" in updates:
                    action = updates["prepare_action"]["prepared_action"]
                    stage = "正在执行制度审核" if action.route == "call_agent" else "正在生成回答"
                    context.on_event(AgentEvent("stage", stage))
        if self._evaluation_sink is not None:
            self._evaluation_sink(
                context.agent_id, context.invocation_id, project_evaluation(state)
            )
        try:
            return ConversationTurnResult.model_validate(state["result"])
        except (KeyError, ValueError) as exc:
            raise AppError("AGENT_OUTPUT_INVALID", "会话结果无效", 502) from exc
