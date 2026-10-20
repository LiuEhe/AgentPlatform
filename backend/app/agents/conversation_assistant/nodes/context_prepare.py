"""会话内容选择策略，委托公共 LLM 能力处理序列化预算。"""

from app.agents.conversation_assistant.schemas import ConversationInput, PendingReview
from app.core.errors import AppError
from app.nodes.llm.context import ContextBudgetError, ContextItem, build_context
from app.schemas.conversation_turn import ConversationTurnInput

COVERAGE_NOTE = "上下文仅包含部分历史和材料；不要声称已阅读所有原文。审核可独立取完整材料。"


def prepare_context(
    turn: ConversationTurnInput,
    capabilities: list[dict[str, object]],
) -> ConversationInput:
    pending = None
    if turn.continuation:
        pending = PendingReview.model_validate(
            turn.continuation.payload
            | {
                "question_message_id": turn.continuation.question_message_id or "",
            }
        )
    base = ConversationInput(
        latest_message_id=turn.latest_message_id,
        messages=[],
        capabilities=capabilities,
        pending_review=pending,
    )
    required, optional = [], []
    selected: list[str] = []
    for index, message in enumerate(turn.messages):
        item = {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "document_ids": list(message.document_ids),
        }
        clipped = False
        if message.agent_call:
            item["agent_result"] = message.agent_call.output[:4000]
            clipped = len(message.agent_call.output) > 4000
        candidate = ContextItem("messages", item, index, already_truncated=clipped)
        if message.id == turn.latest_message_id and message.role == "user":
            required.append(candidate)
            selected.extend(message.document_ids)
        else:
            optional.insert(0, candidate)
    if not required:
        raise AppError("INVALID_AGENT_INPUT", "最新用户消息不存在", 422)
    if pending:
        for ref in (pending.arguments.draft, pending.arguments.standard):
            if ref and ref.kind == "document" and ref.id not in selected:
                selected.append(ref.id)
    documents = {document.id: document for document in turn.documents}
    for index, id in enumerate(dict.fromkeys(selected)):
        document = documents.get(id)
        if document:
            optional.append(
                ContextItem(
                    "documents",
                    {
                        "id": document.id,
                        "filename": document.filename,
                        "chars": len(document.markdown),
                        "content": document.markdown,
                    },
                    index,
                    "content",
                )
            )
    try:
        result = build_context(
            base.model_dump(mode="json"),
            required_items=required,
            optional_items=optional,
            max_chars=24000,
            omission_note=COVERAGE_NOTE,
        )
    except ContextBudgetError as exc:
        raise AppError(
            "CONVERSATION_INPUT_TOO_LONG",
            "消息转换后超过上下文预算，请缩短内容重试",
            422,
        ) from exc
    return ConversationInput.model_validate(result.payload)
