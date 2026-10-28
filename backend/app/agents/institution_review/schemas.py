"""制度审核智能体的专属输入与输出类型。"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.review import ReviewCategory, ReviewReference, Severity


class ReviewMode(StrEnum):
    """制度审核的依据来源。"""

    KNOWLEDGE_BASE = "knowledge_base"
    STANDARD_DOCUMENT = "standard_document"


class Clause(BaseModel):
    """从制度 Markdown 中代码拆分出的条款块。"""

    chapter: str | None = None
    section: str | None = None
    article: str | None = None
    paragraph: str | None = None
    item: str | None = None
    content: str = Field(min_length=1)
    sequence: int = Field(ge=1)


class ReviewChunk(BaseModel):
    """保持原始条款定位的连续执行组。"""

    sequence: int = Field(ge=1)
    clauses: list[Clause] = Field(min_length=1)


class ClauseReviewFinding(BaseModel):
    """单条制度与知识库内容比对后发现的问题。"""

    category: Literal[ReviewCategory.CONFLICT, ReviewCategory.DUPLICATE]
    severity: Severity = Severity.MEDIUM
    description: str = Field(min_length=1)
    reference_indexes: list[int] = Field(default_factory=list)


class ClauseReviewOutput(BaseModel):
    """条款审查模型的结构化输出。"""

    findings: list[ClauseReviewFinding] = Field(default_factory=list)


class ReviewOverviewOutput(BaseModel):
    """简述模型可选择的受控关注类别。"""

    focus: list[Literal["冲突", "重复", "术语"]] = Field(default_factory=list)


class StandardClauseFinding(BaseModel):
    """一个执行组内可定位到原始条款的标准对比发现。"""

    clause_sequence: int = Field(ge=1)
    category: Literal[ReviewCategory.CONFLICT, ReviewCategory.DUPLICATE]
    severity: Severity = Severity.MEDIUM
    description: str
    standard_excerpt: str


class StandardReviewOutput(BaseModel):
    """标准文档对比的批量结构化输出。"""

    findings: list[StandardClauseFinding] = Field(default_factory=list)


class ClauseReview(BaseModel):
    """单条制度的审查结果及其检索引用。"""

    clause: Clause
    findings: list[ClauseReviewFinding] = Field(default_factory=list)
    references: list[ReviewReference] = Field(default_factory=list)


class ChunkReviewResult(BaseModel):
    """一个图任务返回的原条款审核结果，不作为模型输出 schema。"""

    chunk_sequence: int = Field(ge=1)
    reviews: list[ClauseReview]
