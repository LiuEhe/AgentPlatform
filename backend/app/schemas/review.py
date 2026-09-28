"""制度审核接口的数据模型。"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewCategory(StrEnum):
    """审核发现项的类别。"""

    TERMINOLOGY = "terminology"
    CONFLICT = "conflict"
    DUPLICATE = "duplicate"
    COMPLIANCE = "compliance"


class Severity(StrEnum):
    """审核发现项的严重程度。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewRequest(BaseModel):
    """制度审核请求。"""

    model_config = ConfigDict(str_strip_whitespace=False)

    title: str = Field(min_length=1, max_length=200, description="制度标题")
    content: str = Field(min_length=1, max_length=200_000, description="制度正文")

    @field_validator("title", "content")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """拒绝只包含空白字符的标题或正文。"""
        if not value.strip():
            raise ValueError("内容不能为空")
        return value


class FindingDraft(BaseModel):
    """单个审核节点生成的发现项草稿。"""

    clause: str = Field(description="涉及条款或原文片段")
    severity: Severity
    description: str = Field(description="问题说明")
    suggestion: str | None = Field(default=None, description="修改建议")
    evidence: list[str] = Field(default_factory=list, description="参考依据")


class CheckFindings(BaseModel):
    """结构化审核节点输出。"""

    findings: list[FindingDraft] = Field(default_factory=list)


class ClauseList(BaseModel):
    """条款拆分节点输出。"""

    clauses: list[str] = Field(default_factory=list)


class ReviewFinding(BaseModel):
    """对外返回的制度审核发现项。"""

    category: ReviewCategory
    clause: str
    severity: Severity
    description: str
    suggestion: str
    evidence: list[str] = Field(default_factory=list)


class ReviewReference(BaseModel):
    """对外返回的 RAGFlow 检索依据。"""

    content: str
    document_name: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    url: str | None = None
    similarity: float | None = None


class ReviewResponse(BaseModel):
    """制度审核接口响应。"""

    review_id: str
    status: str = "completed"
    findings: list[ReviewFinding]
    summary: str
    references: list[ReviewReference] = Field(default_factory=list)
