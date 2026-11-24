"""FastAPI 应用创建与依赖生命周期管理。"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents import build_agent_registry
from app.api.agents import router as agents_router
from app.api.auth import install_auth_guard
from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.document_exports import router as document_exports_router
from app.api.document_uploads import install_document_upload_limit
from app.api.health import router as health_router
from app.api.reviews import router as reviews_router
from app.api.users import AvatarUploadMiddleware
from app.api.users import router as users_router
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, install_request_logging
from app.core.observability import NullObserver
from app.infrastructure.conversation.active_runs import ActiveRunRegistry
from app.infrastructure.conversation.checkpoints import CheckpointResources
from app.infrastructure.conversation.postgres_store import PostgresConversationStore
from app.infrastructure.database import Database
from app.infrastructure.documents.local_file_store import LocalFileStore
from app.infrastructure.identity.auth_limits import AuthAttemptLimiter
from app.infrastructure.identity.avatar_store import AvatarStore
from app.infrastructure.identity.passwords import PasswordHasher
from app.infrastructure.identity.postgres_store import IdentityStore
from app.infrastructure.langfuse.client import create_observer, shutdown_observer
from app.infrastructure.langfuse.prompts import LangfusePromptResolver
from app.infrastructure.pandoc import PandocRunner
from app.infrastructure.ragflow.client import RagFlowClient
from app.nodes.llm.prompts import PromptResolver
from app.runtime.agent_runtime import AgentRegistry, AgentRuntime
from app.services.agent_catalog_service import AgentCatalogService
from app.services.auth_service import AuthService
from app.services.conversation_service import ConversationService
from app.services.document_export_service import DocumentExportService
from app.services.llm_service import create_llm_service
from app.services.review_service import ReviewService
from app.services.user_service import UserService


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建配置完成的 FastAPI 应用。"""
    app_settings = settings or get_settings()
    configure_logging(app_settings)

    def clear_app_resources(app: FastAPI) -> None:
        app.state.database = None
        app.state.agent_runtime = None
        app.state.review_service = None
        app.state.document_export_service = None
        app.state.conversation_service = None
        app.state.agent_catalog_service = None
        app.state.auth_service = None
        app.state.user_service = None
        app.state.observer = NullObserver()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        async with (
            AsyncExitStack() as resources,
            AsyncExitStack() as network,
            AsyncExitStack() as workloads,
        ):
            resources.callback(clear_app_resources, app)
            observer = create_observer(app_settings)
            resources.push_async_callback(shutdown_observer, observer)
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

            database = Database(app_settings)
            resources.push_async_callback(database.aclose)
            identities = IdentityStore(database)
            passwords = PasswordHasher(
                concurrency=app_settings.auth_hash_concurrency,
                queue_size=app_settings.auth_hash_queue_size,
                queue_timeout=app_settings.auth_hash_queue_timeout_seconds,
            )
            resources.push_async_callback(passwords.aclose)
            auth = AuthService(app_settings, identities, passwords, AuthAttemptLimiter(
                window=app_settings.auth_login_window_seconds,
                ip_failures=app_settings.auth_login_ip_failures,
                account_failures=app_settings.auth_login_account_failures,
                registration_window=app_settings.auth_registration_window_seconds,
                registration_attempts=app_settings.auth_registration_ip_attempts,
                max_keys=app_settings.auth_attempt_max_keys,
            ))
            app.state.auth_service = auth
            user_service = UserService(
                identities, passwords, AvatarStore(app_settings.avatars_root),
            )
            resources.push_async_callback(user_service.aclose)
            app.state.user_service = user_service
            conversation_store = PostgresConversationStore(database)
            checkpoints = CheckpointResources(database.settings, schema=database.schema)
            resources.push_async_callback(checkpoints.aclose)
            files = LocalFileStore(app_settings.documents_root)
            conversation_service = ConversationService(
                app_settings,
                None,
                store=conversation_store,
                checkpoints=checkpoints,
                active_runs=ActiveRunRegistry(max_bytes=app_settings.conversation_transient_max_bytes),
                observer=observer,
                files=files,
            )
            workloads.push_async_callback(conversation_service.aclose)
            database.on_unavailable = conversation_service.storage_unavailable
            app.state.conversation_service = conversation_service
            app.state.agent_catalog_service = AgentCatalogService(conversation_store.list_agents)
            export_service = DocumentExportService(app_settings, PandocRunner(app_settings))
            resources.push_async_callback(export_service.aclose)
            app.state.document_export_service = export_service

            await database.initialize()
            app.state.database = database
            await auth.initialize()
            await checkpoints.open()
            await checkpoints.assert_ready()
            # 删除凭据预检先于会写入业务库的中断恢复。
            await asyncio.to_thread(files.list_deletion_intents)
            await conversation_store.recover_interrupted()
            await conversation_service.recover_deletions()
            await export_service.initialize()

            if not app_settings.readiness_issues():
                # 进入后发生启动异常，退出栈也会关闭客户端。
                client = await network.enter_async_context(httpx.AsyncClient(
                    timeout=httpx.Timeout(60.0, connect=5.0),
                ))
                model = create_llm_service(app_settings)
                rag_client = (
                    RagFlowClient(app_settings, client, observer=observer)
                    if not app_settings.ragflow_issues()
                    else None
                )
                registry = AgentRegistry()
                runtime = AgentRuntime(
                    registry, observer=observer, execution_scope_factory=execution_scope,
                )
                build_agent_registry(
                    model,
                    rag_client,
                    institution_review_concurrency=app_settings.institution_review_concurrency,
                    registry=registry,
                    invoke_agent=runtime.invoke,
                    checkpointer=checkpoints.saver,
                    conversation_max_review_chars=app_settings.max_review_chars,
                    conversation_knowledge_base_configured=not app_settings.ragflow_issues(),
                    observer=observer,
                    graph_config_factory=getattr(observer, "graph_config", None),
                )
                review_service = ReviewService(app_settings, runtime, observer=observer)
                workloads.push_async_callback(review_service.aclose)
                app.state.review_service = review_service
                conversation_service.runtime = runtime
                app.state.agent_runtime = runtime

            yield

    app = FastAPI(
        title="智能体平台后端",
        description="基于 LangGraph 的制度审核与会话助手服务，支持同步审核和 SSE 会话运行。",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    clear_app_resources(app)
    app.add_middleware(AvatarUploadMiddleware, api_prefix=app_settings.api_prefix)
    install_document_upload_limit(
        app, api_prefix=app_settings.api_prefix, max_file_bytes=app_settings.max_upload_bytes,
    )
    install_auth_guard(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-CSRF-Token",
            "X-Auth-Session-ID",
        ],
    )
    install_request_logging(app)
    install_error_handlers(app)
    app.include_router(auth_router, prefix=app_settings.api_prefix)
    app.include_router(users_router, prefix=app_settings.api_prefix)
    app.include_router(health_router)
    app.include_router(agents_router, prefix=app_settings.api_prefix)
    app.include_router(reviews_router, prefix=app_settings.api_prefix)
    app.include_router(document_exports_router, prefix=app_settings.api_prefix)
    app.include_router(conversations_router, prefix=app_settings.api_prefix)
    return app
