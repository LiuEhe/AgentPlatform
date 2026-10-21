"""会话 Agent 的边界适配：校验本轮输入，执行图并返回完整结果。"""

from collections.abc import Mapping

from langgraph.graph.state import CompiledStateGraph

from app.agents.conversation_assistant.evaluation import project_evaluation
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentContext
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
        state = await self._graph.ainvoke({"turn": turn}, config=config)
        if self._evaluation_sink is not None:
            self._evaluation_sink(
                context.agent_id, context.invocation_id, project_evaluation(state)
            )
        try:
            return ConversationTurnResult.model_validate(state["result"])
        except (KeyError, ValueError) as exc:
            raise AppError("AGENT_OUTPUT_INVALID", "会话结果无效", 502) from exc
