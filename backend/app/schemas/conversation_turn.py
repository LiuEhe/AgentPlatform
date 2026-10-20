"""应用服务与会话 Agent 之间的内部契约，不包含 HTTP View 或审核规则。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

NonblankOutput = Annotated[str, StringConstraints(min_length=1, max_length=200000, pattern=r"\S")]


class InternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContinuationState(InternalModel):
    payload: dict[str, object]
    question_message_id: str | None = None


class ChildAgentResult(InternalModel):
    id: str
    agent_id: str
    agent_name: str
    invocation_id: str
    output_type: Literal["markdown", "text", "json"]
    output: NonblankOutput


class TurnMessage(InternalModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    document_ids: tuple[str, ...] = ()
    agent_call: ChildAgentResult | None = None


class TurnDocument(InternalModel):
    id: str
    filename: str
    markdown: str


class ConversationTurnInput(InternalModel):
    latest_message_id: str
    messages: tuple[TurnMessage, ...]
    documents: tuple[TurnDocument, ...] = ()
    continuation: ContinuationState | None = None


class ConversationTurnResult(InternalModel):
    reply: NonblankOutput
    child_call: ChildAgentResult | None = None
    continuation: ContinuationState | None = None
