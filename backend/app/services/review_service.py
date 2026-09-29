"""协调 DOCX 读取、请求校验和制度审核运行时。"""

import logging
import re
from pathlib import Path

from app.core.config import Settings
from app.core.errors import AppError
from app.nodes.document.docx_to_markdown import DocumentReadError, convert_docx_to_markdown
from app.runtime.agent_runtime import AgentRuntime

logger = logging.getLogger(__name__)
_TITLE_PATTERN = re.compile(r"^\s{0,3}#\s+(.+?)\s*$", re.MULTILINE)
_STRUCTURAL_HEADING_PATTERN = re.compile(r"^第[一二三四五六七八九十百千万零〇两0-9]+(?:章|节|条)")


class ReviewService:
    """执行上传制度的读取、校验和同步审核。"""

    def __init__(self, settings: Settings, runtime: AgentRuntime) -> None:
        self._settings = settings
        self._runtime = runtime

    async def review_document(self, filename: str, content: bytes) -> str:
        """将上传 DOCX 转成 Markdown 后运行审核流程。"""
        if Path(filename).suffix.casefold() != ".docx":
            raise AppError("UNSUPPORTED_DOCUMENT_TYPE", "目前只支持 .docx 文件", 415)
        if not content:
            raise AppError("EMPTY_DOCUMENT", "上传文件内容为空", 422)
        if len(content) > self._settings.max_upload_bytes:
            raise AppError("UPLOAD_TOO_LARGE", "上传文件超过大小限制", 413)

        try:
            markdown = convert_docx_to_markdown(content)
        except DocumentReadError as exc:
            raise AppError("INVALID_DOCX", "DOCX 文件无法读取或不包含可审核文本", 422) from exc

        if len(markdown) > self._settings.max_review_chars:
            raise AppError(
                "REVIEW_CONTENT_TOO_LONG",
                f"转换后的制度正文不能超过 {self._settings.max_review_chars} 个字符",
                422,
            )

        title_match = _TITLE_PATTERN.search(markdown)
        document_title = title_match.group(1).strip() if title_match else ""
        if document_title and _STRUCTURAL_HEADING_PATTERN.match(document_title):
            document_title = ""
        title = " ".join((document_title or Path(filename).stem).split())[:200]
        title = title or "未命名制度"

        try:
            report = await self._runtime.review(title, markdown)
        except AppError as exc:
            logger.warning(
                "review_failed code=%s error_type=%s",
                exc.code,
                type(exc).__name__,
            )
            raise

        logger.info("review_completed markdown_chars=%s", len(markdown))
        return report
