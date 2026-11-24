"""协调会话历史、文档和运行用例。"""

import asyncio
from dataclasses import asdict

from app.core.config import Settings
from app.core.errors import AppError
from app.core.observability import NullObserver
from app.infrastructure.conversation.active_runs import ActiveRunRegistry
from app.infrastructure.conversation.checkpoints import CheckpointResources
from app.infrastructure.conversation.postgres_store import PostgresConversationStore
from app.infrastructure.documents.local_file_store import LocalFileStore
from app.runtime.agent_runtime import AgentRuntime
from app.schemas.conversation import (
    AgentCallView,
    FileView,
    MessageCreate,
    MessageView,
    RunView,
    SafeError,
    SessionListView,
    SessionSummaryView,
    SessionView,
)
from app.schemas.conversation_session import SessionMessage, SessionRun
from app.services.conversation_deletion_service import ConversationDeletionService
from app.services.conversation_run_service import ConversationRunService
from app.services.conversation_upload_service import ConversationUploadService


class ConversationService:
    def __init__(
        self,
        settings: Settings,
        runtime: AgentRuntime | None,
        *,
        store: PostgresConversationStore,
        checkpoints: CheckpointResources,
        active_runs: ActiveRunRegistry,
        observer=None,
        files: LocalFileStore | None = None,
    ):
        self.settings = settings
        self._store, self._active = store, active_runs
        self._files = files or LocalFileStore(settings.documents_root)
        self._closed = False
        self._unavailable = False
        self._upload_service = ConversationUploadService(
            settings, store=store, active_runs=active_runs, files=self._files,
            check_open=self._check_open,
        )
        self._runs = ConversationRunService(
            settings, runtime, store=store, active_runs=active_runs, files=self._files,
            checkpoints=checkpoints, observer=observer or NullObserver(),
            check_open=self._check_open, upload_pending=self._upload_service.in_progress,
            is_unavailable=lambda: self._unavailable, storage_unavailable=self.storage_unavailable,
            run_view=self._run_view,
        )
        self._deletions = ConversationDeletionService(
            store=store, active_runs=active_runs, files=self._files, checkpoints=checkpoints,
            check_open=self._check_open, upload_pending=self._upload_service.in_progress,
            run_pending=self._runs.in_progress,
        )

    @property
    def runtime(self) -> AgentRuntime | None:
        return self._runs.runtime

    @runtime.setter
    def runtime(self, runtime: AgentRuntime | None) -> None:
        self._runs.runtime = runtime

    def _check_open(self):
        if self._closed or self._unavailable:
            raise AppError("STORAGE_UNAVAILABLE", "会话服务不可用，请重启服务", 503)

    def _pending_tasks(self):
        return (*self._runs.pending_tasks(), *self._upload_service.pending_tasks())

    def storage_unavailable(self):
        self._unavailable = True
        self._active.fail_unavailable()
        current = asyncio.current_task()
        for task in self._pending_tasks():
            if task is not current:
                task.cancel()

    @staticmethod
    def _file_view(file):
        return FileView(**file.model_dump(exclude={"session_id", "source_path", "content_path"}))

    @staticmethod
    def _message_view(message: SessionMessage):
        call = (
            AgentCallView(
                **message.agent_call.model_dump(exclude={"id"}),
                call_id=message.agent_call.id, status="succeeded"
            )
            if message.agent_call
            else None
        )
        return MessageView(
            message_id=message.message_id,
            sequence=message.sequence,
            role=message.role,
            content=message.content,
            file_ids=list(message.file_ids),
            run_id=message.run_id,
            agent_call=call,
            created_at=message.created_at,
        )

    def _run_view(self, run: SessionRun):
        state = self._active.snapshot(run.run_id)
        return RunView(
            run_id=run.run_id,
            client_message_id=run.request.client_message_id,
            status=run.status,
            stage=state.stage if state else run.stage,
            message=self._message_view(run.message) if run.message else None,
            error=SafeError(code=run.error_code, message=run.error_message)
            if run.error_code
            else None,
        )

    async def create(self, actor):
        self._check_open()
        page = await self._store.create(actor, "conversation_assistant")
        return self._page_view(page)

    async def authorize(self, actor, session_id, *, optional=False):
        await self._store.authorize(actor, session_id, optional=optional)

    async def list(self, actor, agent_id="conversation_assistant", *, limit=20, cursor=None):
        page = await self._store.list(actor, agent_id, limit=limit, cursor=cursor)
        return SessionListView(
            items=[SessionSummaryView(**asdict(s)) for s in page.items],
            next_cursor=page.next_cursor,
        )

    def _page_view(self, page):
        return SessionView(
            **asdict(page.summary),
            messages=[self._message_view(m) for m in page.messages],
            files=[self._file_view(f) for f in page.files],
            active_run_id=page.active_run_id,
            last_sequence=page.last_sequence,
            has_more=page.has_more,
            next_before_sequence=page.next_before_sequence,
            next_after_sequence=page.next_after_sequence,
        )

    async def read(self, actor, session_id, *, limit=50, before_sequence=None, after_sequence=None):
        return self._page_view(
            await self._store.read(actor,
                session_id,
                limit=limit,
                before_sequence=before_sequence,
                after_sequence=after_sequence,
            )
        )

    async def upload(self, actor, session_id: str, filename: str, content: bytes):
        saved = await self._upload_service.upload(actor, session_id, filename, content)
        return self._file_view(saved)

    async def delete(self, actor, session_id: str) -> None:
        await self._deletions.delete(actor, session_id)

    async def recover_deletions(self) -> None:
        await self._deletions.recover_deletions()

    async def submit(self, actor, session_id: str, payload: MessageCreate):
        return await self._runs.submit(actor, session_id, payload)

    async def read_run(self, actor, session_id, run_id):
        return await self._runs.read_run(actor, session_id, run_id)

    async def cancel(self, actor, session_id, run_id):
        return await self._runs.cancel(actor, session_id, run_id)

    async def stream_run(self, actor, session_id, run_id):
        return await self._runs.stream_run(actor, session_id, run_id)

    async def aclose(self):
        self._closed = True
        await self._deletions.wait_for_pending()
        tasks = self._pending_tasks()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await self._runs.finish_remaining()
        finally:
            await self._active.aclose()
