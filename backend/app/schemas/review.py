"""制度审核接口的数据模型。"""

from enum import StrEnum

from pydantic import BaseModel


class ReviewCategory(StrEnum):
    """审核发现项的类别。"""

    TERMINOLOGY = "terminology"
    CONFLICT = "conflict"
    DUPLICATE = "duplicate"


class Severity(StrEnum):
    """审核发现项的严重程度。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewReference(BaseModel):
    """从 RAGFlow 检索并归一化的知识片段。"""

    content: str
    document_name: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    url: str | None = None
    similarity: float | None = None
