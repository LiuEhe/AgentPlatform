"""统一已执行结果，不要求应用服务再次解释意图。"""

from app.agents.conversation_assistant.schemas import PreparedAction
from app.schemas.conversation_turn import ChildAgentResult, ConversationTurnResult


def assemble_result(
    action: PreparedAction,
    reply: str | None,
    child_call: ChildAgentResult | None,
) -> ConversationTurnResult:
    return ConversationTurnResult(
        reply="制度审核助手已完成，结果如下。" if child_call else reply,
        child_call=child_call,
        continuation=action.continuation,
    )
