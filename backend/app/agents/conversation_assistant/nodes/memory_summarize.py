"""当前助手选择需压缩的成功轮次；摘要机械能力由公共节点提供。"""

import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import RemoveMessage

from app.agents.conversation_assistant.config import ConversationAgentConfig
from app.agents.conversation_assistant.graph.state import ConversationGraphState
from app.agents.conversation_assistant.nodes.context_prepare import build_memory_context
from app.agents.conversation_assistant.prompts import CONVERSATION_PROMPTS
from app.agents.conversation_assistant.schemas import ConversationExecutionContext
from app.agents.conversation_assistant.tools.institution_review import review_capabilities
from app.core.errors import AppError
from app.nodes.llm.context import ContextBudgetError
from app.nodes.llm.memory import needs_summary, summarize_history


async def summarize_memory(
    model: BaseChatModel, state: ConversationGraphState, context: ConversationExecutionContext,
    *, config: ConversationAgentConfig,
) -> dict[str, object]:
    messages = state.get("messages", [])
    completed = []
    for message in messages[:-1]:
        details = {
            key: message.additional_kwargs[key]
            for key in ("document_ids", "agent_result", "agent_result_truncated")
            if message.additional_kwargs.get(key)
        }
        if details:
            details["content"] = message.content
            message = message.model_copy(update={
                "content": json.dumps(details, ensure_ascii=False, separators=(",", ":")),
            })
        completed.append(message)
    policy, capabilities = config.memory_policy, review_capabilities(config)
    try:
        build_memory_context(state, context.turn, capabilities)
        fits = True
    except ContextBudgetError:
        fits = False
    if fits and not needs_summary(completed, policy=policy):
        return {}
    count = max(0, len(completed) - policy.recent_turns * 2)
    count = count or min(2, len(completed))
    summary, covered = state.get("summary", ""), state.get("summary_through_sequence", 0)
    removed, previous = [], 0
    while count:
        selected = completed[previous:count]
        result = await summarize_history(
            model, selected, previous_summary=summary, covered_sequence=covered,
            policy=policy, prompt=CONVERSATION_PROMPTS["summary"],
        )
        summary, covered = result.text, result.through_sequence
        removed.extend(result.removed_message_ids)
        candidate = dict(state, summary=summary, messages=messages[count:])
        try:
            build_memory_context(candidate, context.turn, capabilities)
            return {"summary": summary, "summary_through_sequence": covered,
                    "messages": [RemoveMessage(id=id) for id in removed]}
        except ContextBudgetError:
            if count == len(completed):
                break
            previous, count = count, min(count + 2, len(completed))
    raise AppError("CONVERSATION_INPUT_TOO_LONG", "消息转换后超过上下文预算，请缩短内容重试", 422)
