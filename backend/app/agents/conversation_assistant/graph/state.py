"""会话图持久工作记忆与单轮临时输出。"""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.channels import UntrackedValue
from langgraph.graph.message import add_messages

from app.agents.conversation_assistant.schemas import (
    AssembledReply,
    ConversationInput,
    IntentDecision,
    PreparedAction,
)
from app.schemas.conversation_turn import ChildAgentResult


class ConversationGraphState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    summary: str
    summary_through_sequence: int
    pending_review: dict[str, object] | None
    material_catalog: list[dict[str, object]]
    last_completed_run_id: str | None
    model_context: Annotated[ConversationInput, UntrackedValue(ConversationInput)]
    decision: Annotated[IntentDecision, UntrackedValue(IntentDecision)]
    prepared_action: Annotated[PreparedAction, UntrackedValue(PreparedAction)]
    reply: Annotated[str, UntrackedValue(str)]
    child_call: Annotated[ChildAgentResult, UntrackedValue(ChildAgentResult)]
    result: Annotated[AssembledReply, UntrackedValue(AssembledReply)]
