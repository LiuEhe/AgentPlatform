"""协调审核请求校验、运行时调用和安全日志。"""

import logging

from app.core.config import Settings
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentRuntime
from app.schemas.review import ReviewRequest, ReviewResponse

logger = logging.getLogger(__name__)


class ReviewService:
    """执行平台级制度审核应用服务。"""

    def __init__(self, settings: Settings, runtime: AgentRuntime) -> None:
        self._settings = settings
        self._runtime = runtime

    async def review(self, request: ReviewRequest) -> ReviewResponse:
        """验证正文长度后调用 Agent 运行时。"""
        if len(request.content) > self._settings.max_review_chars:
            raise AppError(
                "REVIEW_CONTENT_TOO_LONG",
                f"制度正文不能超过 {self._settings.max_review_chars} 个字符",
                422,
            )
        try:
            response = await self._runtime.review(request)
        except AppError as exc:
            logger.warning(
                "review_failed code=%s error_type=%s",
                exc.code,
                type(exc).__name__,
            )
            raise
        logger.info(
            "review_completed review_id=%s findings=%s references=%s",
            response.review_id,
            len(response.findings),
            len(response.references),
        )
        return response
