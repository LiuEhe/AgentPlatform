"""应用服务与会话 Agent 之间的内部契约，不包含 HTTP View 或审核规则。"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonblankOutput = Annotated[str, StringConstraints(min_length=1, max_length=200000, pattern=r"\S")]


class InternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def conversation_thread_id(agent_id: str, session_id: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", agent_id):
        raise ValueError("Invalid agent identifier")
    return f"{agent_id}:{UUID(session_id)}"


class MaterialReference(InternalModel):
    kind: Literal["document", "user_message"]
    id: str = Field(min_length=1, max_length=128)


class MaterialDescriptor(InternalModel):
    ref: MaterialReference
    title: str
    chars: int = Field(ge=0)
    sequence: int | None = None


class TurnMaterial(InternalModel):
    ref: MaterialReference
    title: str
    content: str


MaterialReader = Callable[[tuple[MaterialReference, ...]], Awaitable[tuple[TurnMaterial, ...]]]


@dataclass(frozen=True)
class ConversationTurnResources:
    read_materials: MaterialReader


class ChildAgentResult(InternalModel):
    id: str
    agent_id: str
    agent_name: str
    invocation_id: str
    output_type: Literal["markdown", "text", "json"]
    output: NonblankOutput


class TurnMessage(InternalModel):
    id: str
    sequence: int = Field(gt=0)
    role: Literal["user", "assistant"]
    content: str
    document_ids: tuple[str, ...] = ()
    agent_call: ChildAgentResult | None = None


class TurnDocument(InternalModel):
    id: str
    filename: str
    markdown: str


class ConversationTurnInput(InternalModel):
    agent_id: str
    session_id: str
    run_id: str
    checkpoint_id: str | None = Field(default=None, min_length=1)
    message: TurnMessage
    assistant_message_id: str = Field(min_length=1)
    assistant_sequence: int = Field(gt=0)
    material_catalog: tuple[MaterialDescriptor, ...] = ()

    @model_validator(mode="after")
    def validate_turn(self):
        conversation_thread_id(self.agent_id, self.session_id)
        if self.message.role != "user" or self.assistant_sequence <= self.message.sequence:
            raise ValueError("Invalid turn message sequence or role")
        return self


class ConversationTurnResult(InternalModel):
    reply: NonblankOutput
    child_call: ChildAgentResult | None = None
    checkpoint_id: str = Field(min_length=1)
    assistant_message_id: str = Field(min_length=1)
    assistant_sequence: int = Field(gt=0)
