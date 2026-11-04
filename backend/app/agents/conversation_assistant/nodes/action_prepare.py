"""确定性业务门控；待补参数只保存在图状态。"""

from collections.abc import Sequence

from app.agents.conversation_assistant.config import ConversationAgentConfig
from app.agents.conversation_assistant.schemas import (
    IntentDecision,
    PendingReview,
    PreparedAction,
    ReviewArguments,
)
from app.agents.conversation_assistant.tools.institution_review import prepare_review
from app.schemas.conversation_turn import MaterialDescriptor


def prepare_action(
    decision: IntentDecision, pending_review: PendingReview | None,
    catalog: Sequence[MaterialDescriptor], config: ConversationAgentConfig, *,
    question_message_id: str,
) -> PreparedAction:
    decision = IntentDecision.model_validate(decision.model_dump())
    if decision.intent != "institution_review":
        return PreparedAction(route=decision.action, decision=decision, question=decision.question)
    args = decision.review_args or ReviewArguments()
    if pending_review and decision.pending_action in {"keep", "update"}:
        args = ReviewArguments.model_validate(
            pending_review.arguments.model_dump() | args.model_dump(exclude_none=True)
        )
        if args.review_mode == "knowledge_base":
            args = args.model_copy(update={"standard": None})
    decision = decision.model_copy(update={"review_args": args})
    prepared = prepare_review(args, catalog, config)
    if decision.action == "call_agent" and not isinstance(prepared, str):
        return PreparedAction(route="call_agent", decision=decision, review=prepared)
    pending = PendingReview(arguments=args, question_message_id=question_message_id)
    if args.review_mode == "knowledge_base" and not config.knowledge_base_configured:
        pending = None
    return PreparedAction(
        route="clarify", decision=decision, pending_review=pending,
        question=prepared if isinstance(prepared, str) else decision.question,
    )
