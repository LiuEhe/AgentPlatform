"""独立的 Markdown 转 Word 下载接口。"""

import logging
from time import monotonic
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import ValidationError

from app.core.errors import AppError, request_id_for
from app.schemas.document_export import DOCX_MEDIA_TYPE, DocumentExportRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["document-export"])


@router.post(
    "/documents/export/docx", response_class=Response,
    responses={200: {"description": "Word 文档", "content": {
        DOCX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}},
    }}},
    openapi_extra={"requestBody": {"required": True, "content": {
        "application/json": {"schema": DocumentExportRequest.model_json_schema()},
    }}},
)
async def export_document_docx(request: Request) -> Response:
    """有界读取 JSON，再委托共享服务完成纯文档转换。"""
    started = monotonic()
    try:
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
            raise AppError("INVALID_EXPORT_INPUT", "请提交 JSON 格式的导出内容", 422)
        body = bytearray()
        limit = request.app.state.settings.document_export_max_body_bytes
        async for chunk in request.stream():
            if len(body) + len(chunk) > limit:
                raise AppError("EXPORT_REQUEST_TOO_LARGE", "导出请求超过大小限制", 413)
            body.extend(chunk)
        try:
            payload = DocumentExportRequest.model_validate_json(bytes(body))
        except ValidationError as exc:
            raise AppError("INVALID_EXPORT_INPUT", "导出内容或标题无效", 422) from exc
        service = getattr(request.app.state, "document_export_service", None)
        if service is None:
            raise AppError("DOCUMENT_EXPORT_UNAVAILABLE", "文档导出服务不可用", 503)
        artifact = await service.export_docx(payload.markdown, title=payload.title)
    except AppError as exc:
        logger.warning(
            "document_export_failed request_id=%s code=%s duration_ms=%s",
            request_id_for(request), exc.code, round((monotonic() - started) * 1000),
        )
        raise
    logger.info(
        "document_export_completed request_id=%s duration_ms=%s input_chars=%s output_bytes=%s",
        request_id_for(request), round((monotonic() - started) * 1000),
        len(payload.markdown), len(artifact.content),
    )
    return Response(
        content=artifact.content, media_type=artifact.media_type,
        headers={
            "Content-Disposition": 'attachment; filename="review-report.docx"; '
            + "filename*=UTF-8''" + quote(artifact.filename, safe=""),
            "Cache-Control": "no-store",
        },
    )
