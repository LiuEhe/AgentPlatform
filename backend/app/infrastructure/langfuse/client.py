"""显式配置客户端；关闭操作不阻塞事件循环。"""

import asyncio
import base64
import logging
import os
from contextlib import contextmanager
from threading import Lock

from app.core.observability import NullObserver
from app.infrastructure.langfuse.costs import pricing_from_settings
from app.infrastructure.langfuse.masking import mask_export, sanitized_exporter
from app.infrastructure.langfuse.tracing import LangfuseObserver

logger = logging.getLogger(__name__)
_configuration_lock = Lock()


@contextmanager
def text_only_sdk():
    # SDK 5 的媒体开关仅提供环境变量，必须在客户端/媒体管理器构造前生效。
    # 仅初始化期间设置并恢复；不修改用户或系统环境配置。
    with _configuration_lock:
        key = "LANGFUSE_MEDIA_UPLOAD_ENABLED"
        previous = os.environ.get(key)
        os.environ[key] = "false"
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def create_observer(settings, *, exporter=None):
    if not settings.langfuse_enabled:
        return NullObserver()
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("langfuse_not_configured")
        return NullObserver()
    try:
        from langfuse import Langfuse
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        public = settings.langfuse_public_key.get_secret_value()
        secret = settings.langfuse_secret_key.get_secret_value()
        secrets = [public, secret, settings.llm_api_key or "", settings.ragflow_api_key or ""]
        if exporter is None:
            auth = base64.b64encode(f"{public}:{secret}".encode()).decode()
            exporter = OTLPSpanExporter(
                endpoint=f"{settings.langfuse_base_url}/api/public/otel/v1/traces",
                headers={"Authorization": f"Basic {auth}", "x-langfuse-ingestion-version": "4"},
                timeout=settings.langfuse_timeout_seconds,
            )
        with text_only_sdk():
            client = Langfuse(
                public_key=public,
                secret_key=secret,
                base_url=settings.langfuse_base_url,
                timeout=settings.langfuse_timeout_seconds,
                environment=settings.app_env,
                sample_rate=settings.langfuse_sample_rate,
                tracing_enabled=True,
                tracer_provider=TracerProvider(
                    sampler=ParentBased(TraceIdRatioBased(settings.langfuse_sample_rate)),
                    resource=Resource(
                        {"service.name": "agent-platform", "langfuse.environment": settings.app_env}
                    ),
                ),
                span_exporter=sanitized_exporter(
                    exporter,
                    capture_content=settings.langfuse_capture_content,
                    secrets=secrets,
                    pricing=pricing_from_settings(settings),
                ),
                mask=lambda data, **_: mask_export(
                    data,
                    # 此回调没有字段路径；不能将 usage.input/output 误判为正文。
                    # 正文开关在具备属性路径的最终 exporter 中执行。
                    capture_content=True,
                    secrets=secrets,
                ),
            )
        return LangfuseObserver(client, public)
    except Exception as exc:
        logger.warning("langfuse_initialize_failed error_type=%s", type(exc).__name__)
        return NullObserver()


async def shutdown_observer(observer):
    shutdown = getattr(observer, "shutdown", None)
    if shutdown is not None:
        try:
            await asyncio.to_thread(shutdown)
        except Exception as exc:
            logger.warning("langfuse_shutdown_failed error_type=%s", type(exc).__name__)
