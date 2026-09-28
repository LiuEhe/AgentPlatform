"""结构化日志和请求 ID 中间件。"""

import logging
from uuid import uuid4

from fastapi import FastAPI, Request

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """配置统一的应用日志格式。"""
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


def install_request_logging(app: FastAPI) -> None:
    """为每个请求生成关联 ID，并只记录路径、状态码和耗时。"""
    logger = logging.getLogger("app.request")

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_complete request_id=%s method=%s path=%s status=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
        )
        return response
