"""临时会话记录，独立于 HTTP 展示和 Agent 的业务状态。"""

from dataclasses import dataclass, field
from typing import Literal

from app.schemas.conversation_turn import ContinuationState, TurnDocument, TurnMessage

SessionRunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class SessionDocument(TurnDocument):
    pass


class SessionMessage(TurnMessage):
    sequence: int
    run_id: str | None = None


@dataclass(frozen=True)
class SessionSubmission:
    client_message_id: str
    content: str
    document_ids: tuple[str, ...] = ()


@dataclass
class SessionRun:
    id: str
    request: SessionSubmission
    status: SessionRunStatus = "queued"
    stage: str = "等待处理"
    message: SessionMessage | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class ConversationSession:
    id: str
    created: float
    interacted: float
    messages: list[SessionMessage] = field(default_factory=list)
    documents: dict[str, SessionDocument] = field(default_factory=dict)
    runs: dict[str, SessionRun] = field(default_factory=dict)
    active_run_id: str | None = None
    continuation: ContinuationState | None = None
    uploading: bool = False
    bytes_used: int = 0


@dataclass(frozen=True)
class SessionSnapshot:
    id: str
    latest_message_id: str
    messages: tuple[SessionMessage, ...]
    documents: dict[str, SessionDocument]
    continuation: ContinuationState | None = None
