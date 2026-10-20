"""会话助手私有的意图、材料引用及动作契约。"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.institution_review.schemas import ReviewMode
from app.schemas.conversation_turn import ContinuationState


class MaterialRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["document", "user_message"]
    id: str = Field(min_length=1, max_length=128)


class ReviewArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: MaterialRef | None = None
    review_mode: ReviewMode | None = None
    standard: MaterialRef | None = None


class PendingReview(BaseModel):
    arguments: ReviewArguments
    question_message_id: str


class ConversationInput(BaseModel):
    latest_message_id: str
    messages: list[dict[str, object]]
    documents: list[dict[str, object]] = Field(default_factory=list)
    capabilities: list[dict[str, object]] = Field(default_factory=list)
    pending_review: PendingReview | None = None
    coverage_note: str = ""


class IntentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal[
        "general_chat", "institution_qa", "institution_review", "unsupported_task", "ambiguous"
    ]
    action: Literal["answer", "clarify", "call_agent"]
    target_agent_id: str | None = None
    review_args: ReviewArguments | None = None
    question: str | None = None
    pending_action: Literal["keep", "update", "clear"] = "clear"

    @model_validator(mode="after")
    def validate_route(self) -> Self:
        if self.intent == "institution_review":
            if self.action not in {"clarify", "call_agent"}:
                raise ValueError("审核意图只能追问或准备调用")
        elif self.intent == "ambiguous":
            if self.action != "clarify" or self.pending_action != "clear":
                raise ValueError("模糊意图必须澄清，不能创建审核任务")
        elif self.action != "answer" or self.pending_action != "clear":
            raise ValueError("非审核意图只能普通回答并清除待审核任务")
        if self.action == "call_agent":
            if self.target_agent_id != "institution_review":
                raise ValueError("仅允许调用制度审核智能体")
        elif self.target_agent_id is not None:
            raise ValueError("非调用动作不能携带目标")
        if self.action == "clarify" and not (self.question or "").strip():
            raise ValueError("澄清必须包含问题")
        return self


class PreparedReview(BaseModel):
    agent_id: Literal["institution_review"] = "institution_review"
    payload: dict[str, object]


class PreparedAction(BaseModel):
    route: Literal["answer", "clarify", "call_agent"]
    decision: IntentDecision
    review: PreparedReview | None = None
    question: str | None = None
    continuation: ContinuationState | None = None
