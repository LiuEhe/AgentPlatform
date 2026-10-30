"""会话应用用例：持久事务、解析、后台任务、取消和 SSE。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import PurePath
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.errors import AppError
from app.core.observability import NullObserver, bind_observation_attributes, observation_attributes
from app.infrastructure.conversation.active_runs import ActiveRunRegistry
from app.infrastructure.conversation.postgres_store import PostgresConversationStore
from app.infrastructure.documents.local_file_store import LocalFileStore
from app.nodes.document.parse import DocumentParseError, parse_docx
from app.runtime.agent_runtime import AgentEvent, AgentRuntime
from app.schemas.conversation import (
    TERMINAL_STATUSES,
    AgentCallView,
    FileView,
    MessageCreate,
    MessageView,
    RunEvent,
    RunView,
    SafeError,
    SessionListView,
    SessionSummaryView,
    SessionView,
)
from app.schemas.conversation_session import (
    RunCompletion,
    SessionFile,
    SessionMessage,
    SessionRun,
    SessionSubmission,
)
from app.schemas.conversation_turn import (
    ConversationTurnInput,
    ConversationTurnResult,
    TurnDocument,
    TurnMessage,
)

logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(
        self,
        settings: Settings,
        runtime: AgentRuntime | None,
        *,
        store: PostgresConversationStore,
        active_runs: ActiveRunRegistry,
        observer=None,
        files: LocalFileStore | None = None,
    ):
        self.settings, self.runtime = settings, runtime
        self._store, self._active = store, active_runs
        self._observer = observer or NullObserver()
        self._files = files or LocalFileStore(settings.documents_root)
        self._slots = asyncio.Semaphore(settings.conversation_concurrency)
        self._admission = asyncio.Semaphore(
            settings.conversation_concurrency + settings.conversation_queue_size
        )
        self._parse_slots = asyncio.Semaphore(2)
        self._tasks: dict[str, asyncio.Task] = {}
        self._uploads: dict[str, asyncio.Task] = {}
        self._submissions: set[asyncio.Task] = set()
        self._run_sessions: dict[str, str] = {}
        self._deletion_tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False
        self._unavailable = False

    def _check_open(self):
        if self._closed or self._unavailable:
            raise AppError("STORAGE_UNAVAILABLE", "会话服务不可用，请重启服务", 503)

    def storage_unavailable(self):
        self._unavailable = True
        self._active.fail_unavailable()
        current = asyncio.current_task()
        for task in (*self._tasks.values(), *self._uploads.values(), *self._submissions):
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

    async def create(self):
        self._check_open()
        page = await self._store.create("conversation_assistant")
        return self._page_view(page)

    async def delete(self, session_id: str) -> None:
        self._check_open()
        try:
            session_id = str(UUID(session_id))
        except (ValueError, TypeError, AttributeError):
            raise AppError("CONVERSATION_NOT_FOUND", "会话不存在", 404) from None
        task = self._deletion_tasks.get(session_id)
        if task is None or task.done():
            task = asyncio.create_task(self._delete_session(session_id))
            self._deletion_tasks[session_id] = task
            def finished(done):
                if self._deletion_tasks.get(session_id) is done:
                    self._deletion_tasks.pop(session_id, None)
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
        await asyncio.shield(task)

    async def _delete_session(self, session_id: str) -> None:
        async with self._active.operation(session_id):
            if session_id in self._uploads:
                raise AppError("CONVERSATION_BUSY", "请等待当前上传结束后再删除", 409)
            target = await self._store.inspect_deletion(session_id)
            if target:
                if target.active_run_id or any(
                    key in self._tasks and not self._tasks[key].done() for key in target.run_ids
                ):
                    raise AppError("CONVERSATION_BUSY", "请等待当前操作结束后再删除", 409)
                try:
                    intent = await asyncio.to_thread(
                        self._files.write_deletion_intent, target.agent_id, session_id
                    )
                except (AppError, OSError):
                    raise AppError("STORAGE_UNAVAILABLE", "无法准备删除，请稍后重试", 503) from None
                try:
                    await self._store.delete_session(session_id)
                except Exception as failure:
                    # 新事务等待原写入结束；查询失败时保留凭据，绝不据超时清理文件。
                    remaining = await self._store.inspect_deletion(session_id)
                    if remaining is not None:
                        try:
                            await asyncio.to_thread(self._files.discard_deletion_intent, session_id)
                        except (AppError, OSError):
                            logger.warning("deletion_intent_retained session_id=%s", session_id)
                        raise failure
            else:
                try:
                    intent = await asyncio.to_thread(self._files.read_deletion_intent, session_id)
                except (AppError, OSError):
                    raise AppError("STORAGE_UNAVAILABLE", "无法核实删除，请稍后重试", 503) from None
                if intent is None:
                    return
            try:
                await asyncio.to_thread(self._files.discard_session, intent.agent_id, session_id)
                await asyncio.to_thread(self._files.discard_deletion_intent, session_id)
            except (AppError, OSError):
                raise AppError(
                    "CONVERSATION_DELETE_INCOMPLETE", "对话已删除，附件清理未完成，请重试清理", 503
                ) from None

    async def recover_deletions(self) -> None:
        try:
            intents = await asyncio.to_thread(self._files.list_deletion_intents)
        except (AppError, OSError) as exc:
            logger.warning("deletion_recovery_unavailable error_type=%s", type(exc).__name__)
            return
        for intent in intents:
            try:
                async with self._active.operation(intent.session_id):
                    target = await self._store.inspect_deletion(intent.session_id)
                    if target is None:
                        await asyncio.to_thread(
                            self._files.discard_session, intent.agent_id, intent.session_id
                        )
                    await asyncio.to_thread(self._files.discard_deletion_intent, intent.session_id)
            except (AppError, OSError) as exc:
                logger.warning(
                    "deletion_recovery_pending session_id=%s error_type=%s",
                    intent.session_id, type(exc).__name__,
                )

    async def list(self, agent_id="conversation_assistant", *, limit=20, cursor=None):
        page = await self._store.list(agent_id, limit=limit, cursor=cursor)
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

    async def read(self, session_id, *, limit=50, before_sequence=None, after_sequence=None):
        return self._page_view(
            await self._store.read(
                session_id,
                limit=limit,
                before_sequence=before_sequence,
                after_sequence=after_sequence,
            )
        )

    async def _parse_upload(self, filename: str, content: bytes) -> TurnDocument:
        if PurePath(filename).suffix.casefold() != ".docx":
            raise AppError("UNSUPPORTED_DOCUMENT_TYPE", "只支持 DOCX 文档", 415)
        if not content:
            raise AppError("EMPTY_DOCUMENT", "文档内容为空", 422)
        if len(content) > self.settings.max_upload_bytes:
            raise AppError("UPLOAD_TOO_LARGE", "文件超过大小限制", 413)
        task = asyncio.create_task(
            asyncio.to_thread(
                parse_docx,
                content,
                max_chars=self.settings.max_review_chars,
            )
        )
        try:
            try:
                markdown = await asyncio.shield(task)
            except asyncio.CancelledError:
                # 转换线程不可中止；重复取消也不能提前归还解析额度。
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not task.cancelled():
                    task.exception()
                raise
        except DocumentParseError as exc:
            status = 413 if exc.code in {"UPLOAD_TOO_LARGE", "REVIEW_CONTENT_TOO_LONG"} else 422
            raise AppError(exc.code, exc.message, status) from exc
        name = " ".join(filename.replace("\\", "/").split("/")[-1].split())[:200]
        return TurnDocument(id=str(uuid4()), filename=name or "文档.docx", markdown=markdown)

    async def upload(self, session_id: str, filename: str, content: bytes):
        self._check_open()
        async with self._active.operation(session_id):
            self._check_open()
            if session_id in self._uploads:
                raise AppError("CONVERSATION_BUSY", "请等待当前上传完成", 409)
            self._active.reserve(len(content))
            self._uploads[session_id] = asyncio.current_task()
        try:
            page = await self._store.read(session_id)
            self._check_open()
            if page.active_run_id:
                raise AppError("CONVERSATION_BUSY", "请等待当前操作完成", 409)
            cancelled = asyncio.Event()
            task = asyncio.create_task(
                self._save_upload(session_id, page, filename, content, cancelled)
            )
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled.set()
                # 文件写入与解析线程无法强制终止，反复取消也必须等待清理结束。
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not task.cancelled():
                    task.exception()
                raise
        finally:
            self._active.release(len(content))
            self._uploads.pop(session_id, None)

    async def _save_upload(self, session_id, page, filename, content, cancelled):
        staged, paths, document = None, None, None
        confirmed = False
        try:
            async with self._parse_slots:
                document = await self._parse_upload(filename, content)
                self._check_open()
                if cancelled.is_set():
                    raise asyncio.CancelledError
                if len(page.files) >= 8 or (
                    sum(f.content_chars for f in page.files) + len(document.markdown) > 100000
                ):
                    raise AppError("CONVERSATION_CAPACITY", "会话材料超过限制", 413)
                staged = await asyncio.to_thread(
                    self._files.stage,
                    page.summary.agent_id,
                    session_id,
                    document.id,
                    content,
                    document.markdown,
                )
                if cancelled.is_set():
                    raise asyncio.CancelledError
                paths = await asyncio.to_thread(self._files.publish, staged)
                if cancelled.is_set():
                    raise asyncio.CancelledError
                metadata = SessionFile(
                    file_id=document.id, session_id=session_id, original_name=document.filename,
                    source_path=paths.source_path, content_path=paths.content_path,
                    size_bytes=len(content), content_chars=len(document.markdown),
                )
                saved = await self._store.add_file(session_id, metadata)
                confirmed = True
                return self._file_view(saved)
        finally:
            if paths and not confirmed:
                try:
                    await self._store.get_file(session_id, document.id)
                except AppError as exc:
                    if exc.code == "MATERIAL_NOT_FOUND":
                        await asyncio.to_thread(self._files.discard_published, paths)
                    else:
                        logger.warning("upload_commit_unconfirmed file_id=%s", document.id)
                except Exception:
                    logger.warning("upload_commit_unconfirmed file_id=%s", document.id)
            if staged:
                await asyncio.to_thread(self._files.discard_staged, staged)

    async def submit(self, session_id: str, payload: MessageCreate):
        self._check_open()
        if self.runtime is None:
            raise AppError("SERVICE_NOT_READY", "聊天模型尚未配置就绪", 503)
        request = SessionSubmission(
            payload.client_message_id, payload.content, tuple(payload.file_ids)
        )
        async with self._active.operation(session_id):
            self._check_open()
            if session_id in self._uploads:
                raise AppError("CONVERSATION_BUSY", "请等待当前上传完成", 409)
            reserved = not self._admission.locked()
            if reserved:
                await self._admission.acquire()
            created = False
            submitting = asyncio.current_task()
            self._submissions.add(submitting)
            try:
                result = await self._store.submit(session_id, request, allow_create=reserved)
                self._check_open()
                created = result.created
                if (
                    not created
                    and result.run.status not in TERMINAL_STATUSES
                    and result.run.run_id not in self._tasks
                    and result.run.run_id not in self._run_sessions
                ):
                    text = "服务中断，本次处理未完成，请重新提交"
                    recovered = await self._store.finish(
                        session_id,
                        result.run.run_id,
                        RunCompletion(
                            "failed",
                            text,
                            error_code="CONVERSATION_INTERRUPTED",
                            error_message=text,
                        ),
                    )
                    return self._run_view(recovered)
                if created:
                    run = result.run
                    run.request_id = observation_attributes.get().get("request_id")
                    self._active.attach(session_id, run)
                    self._run_sessions[run.run_id] = session_id
                    task = asyncio.create_task(self._execute(session_id, run))
                    self._tasks[run.run_id] = task
                    task.add_done_callback(lambda done, key=run.run_id: self._task_done(key, done))
                return self._run_view(result.run)
            finally:
                self._submissions.discard(submitting)
                if reserved and not created:
                    self._admission.release()

    def _task_done(self, run_id, task):
        self._tasks.pop(run_id, None)
        self._admission.release()
        if not task.cancelled():
            task.exception()  # _execute reports errors; consume cancellation-cleanup exceptions.

    async def read_run(self, session_id, run_id):
        return self._run_view(await self._store.read_run(session_id, run_id))

    async def stream_run(self, session_id, run_id) -> AsyncIterator[RunEvent]:
        persisted = await self._store.read_run(session_id, run_id)
        notification = self._active.subscribe(run_id)
        initial = self._active.snapshot(run_id)
        if notification is None and persisted.status not in TERMINAL_STATUSES:
            persisted = await self._store.read_run(session_id, run_id)

        async def events():
            offset = len(initial.text) if initial else 0
            state = (persisted.status, initial.stage if initial else persisted.stage)
            yield RunEvent(
                event="snapshot",
                run=self._run_view(persisted),
                text=initial.text if initial else "",
            )
            while True:
                if self._unavailable:
                    raise AppError("STORAGE_UNAVAILABLE", "回答保存状态未确认，请重新连接", 503)
                active = notification
                run = active.run if active else persisted
                if run.status in TERMINAL_STATUSES:
                    yield RunEvent(event="done", run=self._run_view(run))
                    return
                if active is None:
                    raise AppError("STORAGE_UNAVAILABLE", "运行状态不可用，请重新连接", 503)
                revision = active.revision
                if state != (run.status, active.stage):
                    state = (run.status, active.stage)
                    yield RunEvent(event="state", run=self._run_view(run))
                text = active.text[offset:]
                offset = len(active.text)
                if text:
                    yield RunEvent(event="delta", text=text)
                active.changed.clear()
                if active.revision == revision:
                    await active.changed.wait()

        return events()

    def _receive_event(self, run_id, event: AgentEvent):
        self._check_open()
        if event.kind == "text_delta":
            self._active.append_text(run_id, event.text)
        elif event.kind == "stage":
            self._active.set_stage(run_id, event.text)

    async def _finish(self, session_id, run_id, completion):
        if self._unavailable:
            return
        try:
            committed = await self._store.finish(session_id, run_id, completion)
        except Exception:
            self.storage_unavailable()
            raise
        self._active.complete(run_id, committed)
        self._active.discard(run_id)
        self._run_sessions.pop(run_id, None)
        return committed

    async def _cleanup_run(self, session_id, run_id, completion):
        if self._unavailable:
            return

        async def finish():
            async with asyncio.timeout(10):
                await self._finish(session_id, run_id, completion)

        cleanup = asyncio.create_task(finish())
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        cleanup.result()

    async def cancel(self, session_id, run_id):
        run = await self._store.read_run(session_id, run_id)
        if run.status not in TERMINAL_STATUSES:
            task = self._tasks.get(run_id)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await self._cleanup_run(session_id, run_id, RunCompletion("cancelled", "已停止。"))
        return await self.read_run(session_id, run_id)

    async def _load_materials(self, files):
        documents = []
        for file in files:
            markdown = await asyncio.to_thread(self._files.read_markdown, file.content_path)
            if len(markdown) != file.content_chars:
                raise AppError("FILE_UNAVAILABLE", "材料文件不可用，请重新上传", 503)
            documents.append(
                TurnDocument(id=file.file_id, filename=file.original_name, markdown=markdown)
            )
        return tuple(documents)

    async def _execute(self, session_id, run):
        acquired = False
        attrs = {"session_id": session_id, "run_id": run.run_id, "request_id": run.request_id or ""}
        with bind_observation_attributes(attrs):
            with self._observer.scope("conversation.run", attributes=attrs, detached=True) as span:
                try:
                    async with asyncio.timeout(self.settings.conversation_queue_timeout_seconds):
                        await self._slots.acquire()
                        acquired = True
                    async with asyncio.timeout(self.settings.conversation_run_timeout_seconds):
                        started = await self._store.start(session_id, run.run_id)
                        self._active.update_run(started)
                        self._active.set_stage(run.run_id, "正在处理你的请求")
                        snapshot = await self._store.snapshot(session_id)
                        turn = ConversationTurnInput(
                            latest_message_id=snapshot.latest_message_id,
                            messages=tuple(
                                TurnMessage(
                                    id=m.message_id, role=m.role, content=m.content,
                                    document_ids=m.file_ids, agent_call=m.agent_call,
                                )
                                for m in snapshot.messages
                            ),
                            documents=await self._load_materials(snapshot.files.values()),
                            continuation=snapshot.continuation,
                        )
                        execution = await self.runtime.invoke(
                            "conversation_assistant",
                            turn.model_dump(),
                            on_event=lambda event: self._receive_event(run.run_id, event),
                        )
                        if asyncio.current_task().cancelling():
                            raise asyncio.CancelledError
                        result = ConversationTurnResult.model_validate(execution.output)
                        final = await self._finish(
                            session_id,
                            run.run_id,
                            RunCompletion(
                                "succeeded",
                                result.reply,
                                child_call=result.child_call,
                                continuation=result.continuation,
                            ),
                        )
                        if final:
                            run.status = final.status
                except asyncio.CancelledError:
                    await self._cleanup_run(
                        session_id, run.run_id, RunCompletion("cancelled", "已停止。")
                    )
                    run.status = "cancelled"
                    raise
                except Exception as exc:
                    code = (
                        "CONVERSATION_TIMEOUT"
                        if isinstance(exc, TimeoutError)
                        else exc.code
                        if isinstance(exc, AppError)
                        else "CONVERSATION_FAILED"
                    )
                    message = (
                        "处理超时，请稍后重新提交。"
                        if isinstance(exc, TimeoutError)
                        else exc.message
                        if isinstance(exc, AppError)
                        else "本次处理失败，请稍后重试。"
                    )
                    logger.warning(
                        "conversation_failed run_id=%s code=%s error_type=%s",
                        run.run_id,
                        code,
                        type(exc).__name__,
                    )
                    await self._cleanup_run(
                        session_id,
                        run.run_id,
                        RunCompletion("failed", message, error_code=code, error_message=message),
                    )
                    run.status = "failed"
                finally:
                    if acquired:
                        self._slots.release()
                    span.update(attributes={"status": run.status})

    async def aclose(self):
        self._closed = True
        await asyncio.gather(*list(self._deletion_tasks.values()), return_exceptions=True)
        tasks = list(self._tasks.values()) + list(self._uploads.values()) + list(self._submissions)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for run_id, session_id in list(self._run_sessions.items()):
            await self._cleanup_run(session_id, run_id, RunCompletion("cancelled", "服务已关闭。"))
        await self._active.aclose()
        await self._store.aclose()
