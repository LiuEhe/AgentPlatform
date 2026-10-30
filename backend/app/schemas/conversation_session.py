"""持久会话记录，独立于 HTTP 展示和 Agent 的业务状态。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.conversation_turn import (
    ChildAgentResult,
    ContinuationState,
)

SessionRunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class SessionFile(BaseModel):
    file_id: str
    session_id: str
    original_name: str
    source_path: str
    content_path: str
    size_bytes: int
    content_chars: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionMessage(BaseModel):
    message_id: str
    role: Literal["user", "assistant"]
    content: str
    file_ids: tuple[str, ...] = ()
    agent_call: ChildAgentResult | None = None
    sequence: int
    run_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class SessionSubmission:
    client_message_id: str
    content: str
    file_ids: tuple[str, ...] = ()


@dataclass
class SessionRun:
    run_id: str
    request: SessionSubmission
    request_id: str | None = None
    status: SessionRunStatus = "queued"
    stage: str = "等待处理"
    message: SessionMessage | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    latest_message_id: str
    messages: tuple[SessionMessage, ...]
    files: dict[str, SessionFile]
    continuation: ContinuationState | None = None


@dataclass(frozen=True)
class ChatSessionSummary:
    session_id: str
    agent_id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SessionDeletionTarget:
    session_id: str
    agent_id: str
    run_ids: tuple[str, ...]
    active_run_id: str | None


@dataclass(frozen=True)
class ChatSessionListPage:
    items: list[ChatSessionSummary]
    next_cursor: str | None


@dataclass(frozen=True)
class ChatSessionPage:
    summary: ChatSessionSummary
    messages: list[SessionMessage]
    files: list[SessionFile]
    active_run_id: str | None
    last_sequence: int
    has_more: bool = False
    next_before_sequence: int | None = None
    next_after_sequence: int | None = None


@dataclass(frozen=True)
class SubmissionResult:
    run: SessionRun
    created: bool


@dataclass(frozen=True)
class RunCompletion:
    status: SessionRunStatus
    text: str
    child_call: ChildAgentResult | None = None
    error_code: str | None = None
    error_message: str | None = None
    continuation: ContinuationState | None = None
