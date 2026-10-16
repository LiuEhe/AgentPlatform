"""协调 DOCX 读取、请求校验和制度审核运行时。"""

import logging
import re
from pathlib import Path

from app.agents.institution_review.adapter import INSTITUTION_REVIEW_AGENT_ID
from app.agents.institution_review.schemas import ReviewMode
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

    def _read_document(self, filename: str, content: bytes, *, label: str) -> str:
        """对草稿和标准分别应用同样的文件及正文限制。"""
        if Path(filename).suffix.casefold() != ".docx":
            raise AppError("UNSUPPORTED_DOCUMENT_TYPE", f"{label}只支持 .docx 文件", 415)
        if not content:
            raise AppError("EMPTY_DOCUMENT", f"{label}内容为空", 422)
        if len(content) > self._settings.max_upload_bytes:
            raise AppError("UPLOAD_TOO_LARGE", f"{label}超过大小限制", 413)

        try:
            markdown = convert_docx_to_markdown(content)
        except DocumentReadError as exc:
            raise AppError("INVALID_DOCX", f"{label}无法读取或不包含可审核文本", 422) from exc

        if len(markdown) > self._settings.max_review_chars:
            raise AppError(
                "REVIEW_CONTENT_TOO_LONG",
                f"转换后的{label}正文不能超过 {self._settings.max_review_chars} 个字符",
                422,
            )
        return markdown

    async def review_document(
        self, filename: str, content: bytes, *,
        review_mode: ReviewMode = ReviewMode.KNOWLEDGE_BASE,
        standard_filename: str | None = None,
        standard_content: bytes | None = None,
    ) -> str:
        """校验并转换两种模式的文档，然后调用通用运行时。"""
        try:
            mode = ReviewMode(review_mode)
        except ValueError as exc:
            raise AppError("INVALID_REVIEW_INPUT", "审核方式无效", 422) from exc
        if mode == ReviewMode.STANDARD_DOCUMENT:
            if not standard_filename or standard_content is None:
                raise AppError("STANDARD_DOCUMENT_REQUIRED", "请上传标准文档", 422)
        elif standard_filename is not None or standard_content is not None:
            raise AppError("INVALID_REVIEW_INPUT", "知识库模式不能附带标准文档", 422)

        markdown = self._read_document(filename, content, label="制度草稿")
        payload: dict[str, object] = {}
        if mode == ReviewMode.STANDARD_DOCUMENT:
            standard_markdown = self._read_document(
                standard_filename, standard_content, label="标准文档",
            )
            payload.update(
                review_mode=mode.value,
                standard_name=" ".join(Path(standard_filename).name.split())[:200],
                standard_content=standard_markdown,
            )

        title_match = _TITLE_PATTERN.search(markdown)
        document_title = title_match.group(1).strip() if title_match else ""
        if document_title and _STRUCTURAL_HEADING_PATTERN.match(document_title):
            document_title = ""
        title = " ".join((document_title or Path(filename).stem).split())[:200]
        title = title or "未命名制度"
        if document_title and document_title != title:
            payload["document_title"] = document_title
        payload.update(title=title, content=markdown)

        try:
            execution = await self._runtime.invoke(
                INSTITUTION_REVIEW_AGENT_ID,
                payload,
            )
            report = execution.output
            if not isinstance(report, str):
                raise AppError("AGENT_OUTPUT_INVALID", "制度审核未返回 Markdown 报告", 502)
        except AppError as exc:
            logger.warning(
                "review_failed code=%s error_type=%s",
                exc.code,
                type(exc).__name__,
            )
            raise

        logger.info("review_completed markdown_chars=%s", len(markdown))
        return report
