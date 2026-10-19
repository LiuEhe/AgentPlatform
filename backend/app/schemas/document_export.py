"""文档导出的输入与文件结果。"""

import unicodedata
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocumentExportRequest(BaseModel):
    """严格校验导出内容，不修改正文缩进和换行。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    markdown: str = Field(min_length=1, max_length=200000)
    title: str = Field(default="制度审核报告", min_length=1, max_length=200)

    @field_validator("markdown", "title")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("内容不能为空")
        return value

    @field_validator("title")
    @classmethod
    def reject_controls(cls, value: str) -> str:
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("标题不能包含控制字符")
        return value


@dataclass(frozen=True)
class ExportedDocument:
    """独立于 HTTP 和附件存储的导出结果。"""

    content: bytes
    filename: str
    media_type: str = DOCX_MEDIA_TYPE
