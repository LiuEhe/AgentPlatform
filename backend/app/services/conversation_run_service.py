"""管理会话运行的准入、提交、取消及 SSE 通知。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from app.core.errors import AppError
from app.core.observability import bind_observation_attributes, observation_attributes
from app.runtime.agent_runtime import AgentEvent
from app.schemas.conversation import TERMINAL_STATUSES, MessageCreate, RunEvent
from app.schemas.conversation_session import RunCompletion, SessionFile, SessionSubmission
from app.schemas.conversation_turn import (
    ConversationTurnResources,
    ConversationTurnResult,
    TurnMaterial,
    conversation_thread_id,
)

logger = logging.getLogger(__name__)


class ConversationRunService:
    def __init__(
        self, settings, runtime, *, store, active_runs, files, checkpoints, observer,
        check_open, upload_pending, is_unavailable, storage_unavailable, run_view,
    ):
        self.settings, self.runtime = settings, runtime
        self._store, self._active = store, active_runs
        self._files, self._checkpoints = files, checkpoints
        self._observer = observer
        self._check_open, self._upload_pending = check_open, upload_pending
        self._is_unavailable, self._storage_unavailable = is_unavailable, storage_unavailable
        self._run_view = run_view
        self._slots = asyncio.Semaphore(settings.conversation_concurrency)
        self._admission = asyncio.Semaphore(
            settings.conversation_concurrency + settings.conversation_queue_size
        )
        self._tasks: dict[str, asyncio.Task] = {}
        self._submissions: set[asyncio.Task] = set()
        self._run_sessions: dict[str, str] = {}
        self._run_owners = {}

    def in_progress(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def pending_tasks(self) -> tuple[asyncio.Task, ...]:
        return (*self._tasks.values(), *self._submissions)

    async def finish_remaining(self) -> None:
        for run_id, session_id in list(self._run_sessions.items()):
            await self._cleanup_run(
                self._run_owners[run_id], session_id, run_id,
                RunCompletion("cancelled", "服务已关闭。"),
            )

    async def submit(self, actor, session_id: str, payload: MessageCreate):
        await self._store.authorize(actor, session_id)
        self._check_open()
        if self.runtime is None:
            raise AppError("SERVICE_NOT_READY", "聊天模型尚未配置就绪", 503)
        request = SessionSubmission(
            payload.client_message_id, payload.content, tuple(payload.file_ids)
        )
        async with self._active.operation(session_id):
            self._check_open()
            if self._upload_pending(session_id):
                raise AppError("CONVERSATION_BUSY", "请等待当前上传完成", 409)
            reserved = not self._admission.locked()
            if reserved:
                await self._admission.acquire()
            created = False
            submitting = asyncio.current_task()
            self._submissions.add(submitting)
            try:
                result = await self._store.submit(actor, session_id, request, allow_create=reserved)
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
                        actor.user.user_id, session_id,
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
                    self._run_owners[run.run_id] = actor.user.user_id
                    task = asyncio.create_task(self._execute(actor.user.user_id, session_id, run))
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

    async def read_run(self, actor, session_id, run_id):
        return self._run_view(await self._store.read_run(actor, session_id, run_id))

    async def stream_run(self, actor, session_id, run_id) -> AsyncIterator[RunEvent]:
        persisted = await self._store.read_run(actor, session_id, run_id)
        notification = self._active.subscribe(run_id)
        initial = self._active.snapshot(run_id)
        if notification is None and persisted.status not in TERMINAL_STATUSES:
            persisted = await self._store.read_run(actor, session_id, run_id)

        async def events():
            offset = len(initial.text) if initial else 0
            state = (persisted.status, initial.stage if initial else persisted.stage)
            yield RunEvent(
                event="snapshot",
                run=self._run_view(persisted),
                text=initial.text if initial else "",
            )
            while True:
                if self._is_unavailable():
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

    async def _finish(self, owner, session_id, run_id, completion):
        if self._is_unavailable():
            return
        try:
            committed = await self._store.finish(owner, session_id, run_id, completion)
        except Exception as exc:
            logger.warning(
                "run_finish_unconfirmed run_id=%s error_type=%s", run_id, type(exc).__name__,
            )
            self._storage_unavailable()
            raise
        self._active.complete(run_id, committed)
        self._active.discard(run_id)
        self._run_sessions.pop(run_id, None)
        self._run_owners.pop(run_id, None)
        return committed

    async def _cleanup_run(self, owner, session_id, run_id, completion):
        if self._is_unavailable():
            return

        async def finish():
            async with asyncio.timeout(10):
                await self._finish(owner, session_id, run_id, completion)

        cleanup = asyncio.create_task(finish())
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        cleanup.result()

    async def cancel(self, actor, session_id, run_id):
        await self._store.authorize(actor, session_id, write=True)
        run = await self._store.read_run(actor, session_id, run_id)
        if run.status not in TERMINAL_STATUSES:
            task = self._tasks.get(run_id)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await self._cleanup_run(
                actor.user.user_id, session_id, run_id, RunCompletion("cancelled", "已停止。")
            )
        return await self.read_run(actor, session_id, run_id)

    def _material_reader(self, owner, session_id):
        async def read(refs):
            sources = await self._store.read_material_sources(owner, session_id, refs)
            result = []
            for ref, source in zip(refs, sources, strict=True):
                if isinstance(source, SessionFile):
                    text = await asyncio.to_thread(self._files.read_markdown, source.content_path)
                    if len(text) != source.content_chars:
                        raise AppError("FILE_UNAVAILABLE", "材料文件不可用，请重新上传", 503)
                    title = source.original_name
                else:
                    text, title = source.content, "粘贴正文"
                result.append(TurnMaterial(ref=ref, title=title, content=text))
            return tuple(result)
        return read

    async def _execute(self, owner, session_id, run):
        acquired = False
        attrs = {"session_id": session_id, "run_id": run.run_id, "request_id": run.request_id or ""}
        with bind_observation_attributes(attrs):
            with self._observer.scope("conversation.run", attributes=attrs, detached=True) as span:
                try:
                    async with asyncio.timeout(self.settings.conversation_queue_timeout_seconds):
                        await self._slots.acquire()
                        acquired = True
                    async with asyncio.timeout(self.settings.conversation_run_timeout_seconds):
                        started = await self._store.start(owner, session_id, run.run_id)
                        self._active.update_run(started)
                        self._active.set_stage(run.run_id, "正在处理你的请求")
                        turn = await self._store.load_turn(
                            owner, session_id, run.run_id, assistant_message_id=str(uuid4()),
                        )
                        if turn.checkpoint_id is None:
                            async with self._active.operation(session_id):
                                await self._checkpoints.delete_thread(
                                    conversation_thread_id(turn.agent_id, session_id),
                                )
                        execution = await self.runtime.invoke(
                            turn.agent_id,
                            turn.model_dump(),
                            on_event=lambda event: self._receive_event(run.run_id, event),
                            resources=ConversationTurnResources(
                                self._material_reader(owner, session_id)
                            ),
                        )
                        if asyncio.current_task().cancelling():
                            raise asyncio.CancelledError
                        result = ConversationTurnResult.model_validate(execution.output)
                        if (result.assistant_message_id != turn.assistant_message_id
                                or result.assistant_sequence != turn.assistant_sequence):
                            raise AppError("AGENT_OUTPUT_INVALID", "会话结果标识不一致", 502)
                        final = await self._finish(
                            owner, session_id,
                            run.run_id,
                            RunCompletion(
                                "succeeded",
                                result.reply,
                                child_call=result.child_call,
                                assistant_message_id=result.assistant_message_id,
                                assistant_sequence=result.assistant_sequence,
                                expected_checkpoint_id=turn.checkpoint_id,
                                memory_checkpoint_id=result.checkpoint_id,
                            ),
                        )
                        if final:
                            run.status = final.status
                except asyncio.CancelledError:
                    await self._cleanup_run(
                        owner, session_id, run.run_id, RunCompletion("cancelled", "已停止。")
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
                        owner, session_id,
                        run.run_id,
                        RunCompletion("failed", message, error_code=code, error_message=message),
                    )
                    run.status = "failed"
                finally:
                    if acquired:
                        self._slots.release()
                    span.update(attributes={"status": run.status})
