"""接收制度草稿并以 Markdown 返回审核报告。"""

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response

from app.agents.institution_review.schemas import ReviewMode
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
async def create_review(
    request: Request,
    file: UploadFile = File(...),
    review_mode: Annotated[ReviewMode, Form()] = ReviewMode.KNOWLEDGE_BASE,
    standard_file: UploadFile | None = File(None),
) -> Response:
    """接收草稿及可选标准文档，同步返回 Markdown 报告。"""
    settings = request.app.state.settings
    try:
        if review_mode == ReviewMode.STANDARD_DOCUMENT and standard_file is None:
            raise AppError("STANDARD_DOCUMENT_REQUIRED", "请上传标准文档", 422)
        if review_mode == ReviewMode.KNOWLEDGE_BASE and standard_file is not None:
            raise AppError("INVALID_REVIEW_INPUT", "知识库模式不能附带标准文档", 422)
        runtime = getattr(request.app.state, "agent_runtime", None)
        if runtime is None:
            raise AppError("SERVICE_NOT_READY", "模型服务尚未配置就绪", 503)
        if review_mode == ReviewMode.KNOWLEDGE_BASE and settings.ragflow_issues():
            raise AppError("RAGFLOW_NOT_CONFIGURED", "知识库审核所需的 RAGFlow 配置不完整", 503)

        content = await file.read(settings.max_upload_bytes + 1)
        standard_content = None
        if standard_file is not None:
            standard_content = await standard_file.read(settings.max_upload_bytes + 1)
        service = ReviewService(
            settings, runtime, observer=getattr(request.app.state, "observer", None)
        )
        report = await service.review_document(
            file.filename or "",
            content,
            review_mode=review_mode,
            standard_filename=standard_file.filename if standard_file is not None else None,
            standard_content=standard_content,
        )
        return Response(content=report, media_type="text/markdown")
    finally:
        await file.close()
        if standard_file is not None:
            await standard_file.close()
