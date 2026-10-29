"""会话 HTTP 数据契约；附件可选，业务输出与聊天消息分开。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_message_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=12000)
    document_ids: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("content", "client_message_id")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("内容不能为空")
        return value

    @field_validator("document_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(not item for item in value):
            raise ValueError("文档引用无效")
        return value


class SafeError(BaseModel):
    code: str
    message: str


class DocumentView(BaseModel):
    id: str
    filename: str
    chars: int


class AgentCallView(BaseModel):
    id: str
    agent_id: str
    agent_name: str
    invocation_id: str | None = None
    status: RunStatus
    output_type: Literal["markdown", "text", "json"] | None = None
    output: str | None = None
    error: SafeError | None = None


class MessageView(BaseModel):
    id: str
    sequence: int
    role: Literal["user", "assistant"]
    content: str
    document_ids: list[str] = Field(default_factory=list)
    run_id: str | None = None
    agent_call: AgentCallView | None = None


class RunView(BaseModel):
    id: str
    client_message_id: str
    status: RunStatus
    stage: str
    message: MessageView | None = None
    error: SafeError | None = None


class ConversationView(BaseModel):
    id: str
    expires_in_seconds: int
    messages: list[MessageView]
    documents: list[DocumentView]
    active_run_id: str | None
    last_sequence: int


class RunEvent(BaseModel):
    event: Literal["snapshot", "delta", "state", "done"]
    run: RunView | None = None
    text: str = ""
