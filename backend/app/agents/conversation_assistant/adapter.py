"""从确认检查点执行增量输入，返回完成位置；不操作业务归档。"""

from collections.abc import Mapping

from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph

from app.agents.conversation_assistant.evaluation import project_evaluation
from app.agents.conversation_assistant.schemas import ConversationExecutionContext
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentContext, AgentEvent
from app.schemas.conversation_turn import (
    ConversationTurnInput,
    ConversationTurnResources,
    ConversationTurnResult,
    conversation_thread_id,
)


class ConversationAssistantAgent:
    def __init__(
        self, graph: CompiledStateGraph, *, graph_config_factory=None, evaluation_sink=None
    ):
        self._graph = graph
        self._graph_config_factory = graph_config_factory
        self._evaluation_sink = evaluation_sink

    async def invoke(
        self, payload: Mapping[str, object], context: AgentContext
    ) -> ConversationTurnResult:
        try:
            turn = ConversationTurnInput.model_validate(payload)
        except ValueError as exc:
            raise AppError("INVALID_AGENT_INPUT", "会话输入无效", 422) from exc
        if context.agent_id != turn.agent_id or not isinstance(
            context.resources, ConversationTurnResources
        ):
            raise AppError("INVALID_AGENT_INPUT", "会话执行资源无效", 422)
        config = (
            dict(self._graph_config_factory(context) or {}) if self._graph_config_factory else {}
        )
        identity = {"thread_id": conversation_thread_id(turn.agent_id, turn.session_id)}
        configurable = dict(config.get("configurable", {}))
        configurable.pop("checkpoint_id", None)
        configurable.update(identity)
        config["configurable"] = configurable
        if turn.checkpoint_id is not None:
            configurable["checkpoint_id"] = turn.checkpoint_id
            accepted = await self._graph.aget_state(config)
            if (
                not accepted.values
                or accepted.next
                or accepted.config["configurable"].get("checkpoint_id") != turn.checkpoint_id
            ):
                raise AppError("STORAGE_UNAVAILABLE", "已确认记忆不可用，请检查存储", 503)
        user = HumanMessage(
            id=turn.message.id, content=turn.message.content,
            additional_kwargs={"sequence": turn.message.sequence, "run_id": turn.run_id,
                               "document_ids": list(turn.message.document_ids)},
        )
        state = {}
        async for part in self._graph.astream(
            {"messages": [user]}, config=config,
            context=ConversationExecutionContext(turn, context.resources.read_materials),
            stream_mode=["messages", "values", "updates"], version="v2", durability="sync",
        ):
            if part["type"] == "values":
                state = part["data"]
            elif part["type"] == "messages" and context.on_event:
                chunk, metadata = part["data"]
                if metadata.get("langgraph_node") == "reply_chat" and chunk.text:
                    context.on_event(AgentEvent("text_delta", chunk.text))
            elif part["type"] == "updates" and context.on_event:
                updates = part["data"]
                if "prepare_context" in updates:
                    context.on_event(AgentEvent("stage", "正在理解你的问题"))
                if "prepare_action" in updates:
                    action = updates["prepare_action"]["prepared_action"]
                    context.on_event(
                        AgentEvent(
                            "stage",
                            "正在执行制度审核" if action.route == "call_agent" else "正在生成回答",
                        )
                    )
        latest_config = dict(config, configurable=identity)
        final = await self._graph.aget_state(latest_config)
        if (final.next or final.values.get("last_completed_run_id") != turn.run_id
                or not final.values.get("messages")
                or final.values["messages"][-1].id != turn.assistant_message_id):
            raise AppError("STORAGE_UNAVAILABLE", "本轮记忆尚未确认", 503)
        if self._evaluation_sink is not None:
            self._evaluation_sink(
                context.agent_id, context.invocation_id, project_evaluation(state)
            )
        try:
            result = state["result"]
            return ConversationTurnResult(
                reply=result.reply,
                child_call=result.child_call,
                checkpoint_id=final.config["configurable"]["checkpoint_id"],
                assistant_message_id=turn.assistant_message_id,
                assistant_sequence=turn.assistant_sequence,
            )
        except (KeyError, ValueError) as exc:
            raise AppError("AGENT_OUTPUT_INVALID", "会话结果无效", 502) from exc
