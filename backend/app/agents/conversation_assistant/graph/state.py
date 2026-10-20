"""单次调用的业务状态，不保存会话锁、任务或存储对象。"""

from typing import TypedDict

from app.agents.conversation_assistant.nodes.material_prepare import Materials
from app.agents.conversation_assistant.schemas import (
    ConversationInput,
    IntentDecision,
    PreparedAction,
)
from app.schemas.conversation_turn import (
    ChildAgentResult,
    ConversationTurnInput,
    ConversationTurnResult,
)


class ConversationGraphState(TypedDict, total=False):
    turn: ConversationTurnInput
    materials: Materials
    model_context: ConversationInput
    decision: IntentDecision
    prepared_action: PreparedAction
    reply: str
    child_call: ChildAgentResult
    result: ConversationTurnResult
