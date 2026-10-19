"""FastAPI 应用创建与依赖生命周期管理。"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents import build_agent_registry
from app.api.agents import router as agents_router
from app.api.document_exports import router as document_exports_router
from app.api.health import router as health_router
from app.api.reviews import router as reviews_router
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, install_request_logging
from app.infrastructure.pandoc import PandocRunner
from app.infrastructure.ragflow.client import RagFlowClient
from app.runtime.agent_runtime import AgentRuntime
from app.services.document_export_service import DocumentExportService
from app.services.llm_service import create_llm_service


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建配置完成的 FastAPI 应用。"""
    app_settings = settings or get_settings()
    configure_logging(app_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.settings = app_settings
        app.state.agent_runtime = None
        export_service = DocumentExportService(app_settings, PandocRunner(app_settings))
        app.state.document_export_service = export_service
        try:
            await export_service.initialize()
            if not app_settings.readiness_issues():
                timeout = httpx.Timeout(60.0, connect=5.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    model = create_llm_service(app_settings)
                    rag_client = (
                        RagFlowClient(app_settings, client)
                        if not app_settings.ragflow_issues() else None
                    )
                    registry = build_agent_registry(
                        model, rag_client,
                        institution_review_concurrency=app_settings.institution_review_concurrency,
                    )
                    app.state.agent_runtime = AgentRuntime(registry)
                    yield
            else:
                yield
        finally:
            app.state.agent_runtime = None
            try:
                await export_service.aclose()
            finally:
                app.state.document_export_service = None

    app = FastAPI(
        title="智能体平台后端",
        description="基于 LangGraph 的同步制度审核服务",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.agent_runtime = None
    app.state.document_export_service = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    install_request_logging(app)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(agents_router, prefix=app_settings.api_prefix)
    app.include_router(reviews_router, prefix=app_settings.api_prefix)
    app.include_router(document_exports_router, prefix=app_settings.api_prefix)
    return app
