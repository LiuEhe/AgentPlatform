"""FastAPI 应用创建与依赖生命周期管理。"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents import build_agent_registry
from app.api.agents import router as agents_router
from app.api.conversations import router as conversations_router
from app.api.document_exports import router as document_exports_router
from app.api.health import router as health_router
from app.api.reviews import router as reviews_router
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, install_request_logging
from app.core.observability import NullObserver
from app.infrastructure.conversation.active_runs import ActiveRunRegistry
from app.infrastructure.conversation.postgres_store import PostgresConversationStore
from app.infrastructure.documents.local_file_store import LocalFileStore
from app.infrastructure.langfuse.client import create_observer, shutdown_observer
from app.infrastructure.langfuse.prompts import LangfusePromptResolver
from app.infrastructure.pandoc import PandocRunner
from app.infrastructure.ragflow.client import RagFlowClient
from app.nodes.llm.prompts import PromptResolver
from app.runtime.agent_runtime import AgentRegistry, AgentRuntime
from app.services.agent_catalog_service import AgentCatalogService
from app.services.conversation_service import ConversationService
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
        observer = create_observer(app_settings)
        app.state.observer = observer
        resolver = (
            LangfusePromptResolver(
                observer.client,
                label=app_settings.langfuse_prompt_label,
                cache_ttl_seconds=app_settings.langfuse_prompt_cache_ttl_seconds,
            )
            if app_settings.langfuse_prompts_enabled and hasattr(observer, "client")
            else PromptResolver()
        )

        @asynccontextmanager
        async def execution_scope(context):
            async with resolver.session():
                yield

        conversation_store = PostgresConversationStore(
            app_settings,
            on_unavailable=lambda: conversation_service.storage_unavailable(),
        )
        conversation_service = ConversationService(
            app_settings,
            None,
            store=conversation_store,
            active_runs=ActiveRunRegistry(max_bytes=app_settings.conversation_transient_max_bytes),
            observer=observer,
            files=LocalFileStore(app_settings.documents_root),
        )
        app.state.conversation_service = conversation_service
        app.state.agent_catalog_service = AgentCatalogService(conversation_store.list_agents)
        export_service = DocumentExportService(app_settings, PandocRunner(app_settings))
        app.state.document_export_service = export_service
        try:
            await conversation_store.initialize()
            await conversation_store.recover_interrupted()
            await export_service.initialize()
            if not app_settings.readiness_issues():
                timeout = httpx.Timeout(60.0, connect=5.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    model = create_llm_service(app_settings)
                    rag_client = (
                        RagFlowClient(app_settings, client, observer=observer)
                        if not app_settings.ragflow_issues()
                        else None
                    )
                    registry = AgentRegistry()
                    runtime = AgentRuntime(
                        registry,
                        observer=observer,
                        execution_scope_factory=execution_scope,
                    )
                    build_agent_registry(
                        model,
                        rag_client,
                        institution_review_concurrency=app_settings.institution_review_concurrency,
                        registry=registry,
                        invoke_agent=runtime.invoke,
                        conversation_max_review_chars=app_settings.max_review_chars,
                        conversation_knowledge_base_configured=not app_settings.ragflow_issues(),
                        observer=observer,
                        graph_config_factory=getattr(observer, "graph_config", None),
                    )
                    app.state.agent_runtime = runtime
                    conversation_service.runtime = app.state.agent_runtime
                    try:
                        yield
                    finally:
                        await conversation_service.aclose()
            else:
                yield
        finally:
            try:
                await conversation_service.aclose()
            finally:
                await conversation_store.aclose()
            await shutdown_observer(observer)
            app.state.conversation_service = None
            app.state.agent_catalog_service = None
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
    app.state.conversation_service = None
    app.state.agent_catalog_service = None
    app.state.observer = NullObserver()
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
    app.include_router(conversations_router, prefix=app_settings.api_prefix)
    return app
