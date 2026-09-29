"""接收制度草稿并以 Markdown 返回审核报告。"""

from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import Response

from app.core.errors import AppError
from app.services.review_service import ReviewService

router = APIRouter(tags=["institution-review"])


@router.post(
    "/reviews",
    response_class=Response,
    responses={
        200: {
            "description": "制度审核 Markdown 报告",
            "content": {"text/markdown": {"schema": {"type": "string"}}},
        }
    },
)
async def create_review(request: Request, file: UploadFile = File(...)) -> Response:
    """接收 DOCX 制度草稿并同步返回 Markdown 报告。"""
    settings = request.app.state.settings
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise AppError("SERVICE_NOT_READY", "模型或 RAGFlow 服务尚未配置就绪", 503)

    filename = file.filename or ""
    if Path(filename).suffix.casefold() != ".docx":
        raise AppError("UNSUPPORTED_DOCUMENT_TYPE", "目前只支持 .docx 文件", 415)

    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise AppError("UPLOAD_TOO_LARGE", "上传文件超过大小限制", 413)

    service = ReviewService(settings, runtime)
    report = await service.review_document(filename, content)
    return Response(content=report, media_type="text/markdown")
