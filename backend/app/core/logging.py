"""结构化日志和请求 ID 中间件。"""

import logging
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Request

from app.core.config import Settings
from app.core.observability import NullObserver, bind_observation_attributes


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
        observer = getattr(app.state, "observer", NullObserver())
        selected = request.method == "POST" and (
            request.url.path.startswith(f"{app.state.settings.api_prefix}/sessions")
            or request.url.path == f"{app.state.settings.api_prefix}/reviews"
        )
        active = observer if selected else NullObserver()
        started, status, trace_id = monotonic(), 500, None
        with bind_observation_attributes({"request_id": request_id}):
            try:
                with active.scope(
                    "http.request",
                    attributes={
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.scope.get("route", request.url.path).__str__(),
                    },
                ) as span:
                    trace_id = span.trace_id
                    response = await call_next(request)
                    status = response.status_code
                    span.update(attributes={"status_code": status})
                    response.headers["X-Request-ID"] = request_id
                    return response
            finally:
                logger.info(
                    "request_complete request_id=%s trace_id=%s method=%s path=%s "
                    "status=%s elapsed_ms=%.2f",
                    request_id,
                    trace_id,
                    request.method,
                    request.url.path,
                    status,
                    (monotonic() - started) * 1000,
                )
