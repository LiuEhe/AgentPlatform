"""确定性业务门控与待补审核参数续接。"""

from collections.abc import Mapping

from app.agents.conversation_assistant.config import ConversationAgentConfig
from app.agents.conversation_assistant.schemas import (
    IntentDecision,
    PreparedAction,
    ReviewArguments,
)
from app.agents.conversation_assistant.tools.institution_review import prepare_review
from app.schemas.conversation_turn import ContinuationState, ConversationTurnInput


def prepare_action(
    turn: ConversationTurnInput,
    decision: IntentDecision,
    materials: Mapping[tuple[str, str], tuple[str, str]],
    config: ConversationAgentConfig,
) -> PreparedAction:
    decision = IntentDecision.model_validate(decision.model_dump())
    if decision.intent != "institution_review":
        return PreparedAction(route=decision.action, decision=decision, question=decision.question)
    args = decision.review_args or ReviewArguments()
    if turn.continuation and decision.pending_action in {"keep", "update"}:
        previous = ReviewArguments.model_validate(turn.continuation.payload["arguments"])
        args = ReviewArguments.model_validate(
            previous.model_dump() | args.model_dump(exclude_none=True)
        )
        if args.review_mode == "knowledge_base":
            # 模式切换后废弃待补任务中的旧标准，不能继续传给知识库审核。
            args = args.model_copy(update={"standard": None})
    decision = decision.model_copy(update={"review_args": args})
    prepared = prepare_review(args, materials, config)
    if decision.action == "call_agent" and not isinstance(prepared, str):
        return PreparedAction(route="call_agent", decision=decision, review=prepared)
    continuation = ContinuationState(payload={"arguments": args.model_dump(mode="json")})
    if args.review_mode == "knowledge_base" and not config.knowledge_base_configured:
        continuation = None
    return PreparedAction(
        route="clarify",
        decision=decision,
        continuation=continuation,
        question=prepared if isinstance(prepared, str) else decision.question,
    )
