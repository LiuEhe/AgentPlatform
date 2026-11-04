"""助手记忆与材料选择；序列化预算复用公共 LLM 能力。"""

from app.agents.conversation_assistant.config import MAX_CONTEXT_CHARS
from app.agents.conversation_assistant.graph.state import ConversationGraphState
from app.agents.conversation_assistant.schemas import (
    ConversationExecutionContext,
    ConversationInput,
    PendingReview,
)
from app.core.errors import AppError
from app.nodes.llm.context import ContextBudgetError, ContextItem, build_context
from app.schemas.conversation_turn import ConversationTurnInput, MaterialReference

COVERAGE_NOTE = "上下文仅包含部分历史和材料；不要声称已阅读所有原文。审核可独立取完整材料。"


def build_memory_context(
    state: ConversationGraphState, turn: ConversationTurnInput,
    capabilities: list[dict[str, object]],
) -> ConversationInput:
    pending = (
        PendingReview.model_validate(state["pending_review"])
        if state.get("pending_review")
        else None
    )
    base = ConversationInput(
        latest_message_id=turn.message.id, messages=[], capabilities=capabilities,
        pending_review=pending, summary=state.get("summary", ""),
    )
    required, optional = [], []
    for index, message in enumerate(state.get("messages", [])):
        item = {
            "id": message.id,
            "role": "user" if message.type == "human" else "assistant",
            "content": message.content,
            "document_ids": message.additional_kwargs.get("document_ids", []),
        }
        if "agent_result" in message.additional_kwargs:
            item["agent_result"] = message.additional_kwargs["agent_result"]
        required.append(
            ContextItem(
                "messages",
                item,
                index,
                already_truncated=message.additional_kwargs.get("agent_result_truncated", False),
            )
        )
    if not any(item.value["id"] == turn.message.id for item in required):
        raise AppError("INVALID_AGENT_INPUT", "最新用户消息不存在", 422)
    pinned = {("document", id) for id in turn.message.document_ids}
    if pending:
        pinned.update(
            (ref.kind, ref.id)
            for ref in (pending.arguments.draft, pending.arguments.standard)
            if ref
        )
    for index, descriptor in enumerate(state.get("material_catalog", [])):
        candidate = ContextItem("material_catalog", descriptor, index)
        ref = descriptor["ref"]
        (required if (ref["kind"], ref["id"]) in pinned else optional).append(candidate)
    result = build_context(
        base.model_dump(mode="json"),
        required_items=required,
        optional_items=list(reversed(optional)),
        max_chars=MAX_CONTEXT_CHARS,
        omission_note=COVERAGE_NOTE,
    )
    return ConversationInput.model_validate(result.payload)


async def prepare_context(
    state: ConversationGraphState, context: ConversationExecutionContext,
    capabilities: list[dict[str, object]],
) -> ConversationInput:
    try:
        base = build_memory_context(state, context.turn, capabilities)
        selected = [
            MaterialReference(kind="document", id=id) for id in context.turn.message.document_ids
        ]
        if base.pending_review:
            for ref in (
                base.pending_review.arguments.draft,
                base.pending_review.arguments.standard,
            ):
                if ref and ref.kind == "document" and ref not in selected:
                    selected.append(ref)
        materials = await context.read_materials(tuple(selected)) if selected else ()
        optional = [ContextItem("documents", {
            "id": m.ref.id, "filename": m.title, "chars": len(m.content), "content": m.content,
        }, index, "content") for index, m in enumerate(materials)]
        result = build_context(
            base.model_dump(mode="json"), required_items=[], optional_items=optional,
            max_chars=MAX_CONTEXT_CHARS, omission_note=COVERAGE_NOTE,
        )
        if base.coverage_note:
            result.payload["coverage_note"] = COVERAGE_NOTE
        return ConversationInput.model_validate(result.payload)
    except ContextBudgetError as exc:
        raise AppError(
            "CONVERSATION_INPUT_TOO_LONG", "消息转换后超过上下文预算，请缩短内容重试", 422
        ) from exc
