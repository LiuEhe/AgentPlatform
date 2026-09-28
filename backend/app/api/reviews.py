"""制度审核同步 API。"""

from fastapi import APIRouter, Request

from app.core.errors import AppError
from app.schemas.review import ReviewRequest, ReviewResponse
from app.services.review_service import ReviewService

router = APIRouter(tags=["institution-review"])


@router.post("/reviews", response_model=ReviewResponse)
async def create_review(payload: ReviewRequest, request: Request) -> ReviewResponse:
    """接收制度文本并同步返回审核结果。"""
    settings = request.app.state.settings
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise AppError("SERVICE_NOT_READY", "模型或 RAGFlow 服务尚未配置就绪", 503)
    service = ReviewService(settings, runtime)
    return await service.review(payload)
