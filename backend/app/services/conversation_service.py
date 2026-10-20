"""会话应用服务：临时记录、上传、任务生命周期及 HTTP 契约映射。"""

import asyncio
import logging
from pathlib import PurePath
from uuid import uuid4

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.conversation.in_memory_store import InMemoryConversationStore
from app.nodes.document.parse import DocumentParseError, parse_docx
from app.runtime.agent_runtime import AgentRuntime
from app.schemas.conversation import (
    TERMINAL_STATUSES,
    AgentCallView,
    ConversationView,
    DocumentView,
    MessageCreate,
    MessageView,
    RunView,
    SafeError,
)
from app.schemas.conversation_session import (
    SessionDocument,
    SessionMessage,
    SessionRun,
    SessionSubmission,
)
from app.schemas.conversation_turn import (
    ChildAgentResult,
    ContinuationState,
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
        store: InMemoryConversationStore,
    ):
        self.settings = settings
        self.runtime = runtime
        self._store = store
        self._slots = asyncio.Semaphore(settings.conversation_concurrency)
        self._parse_slots = asyncio.Semaphore(2)
        self._tasks: dict[str, asyncio.Task] = {}
        self._uploads: dict[str, asyncio.Task] = {}
        self._stop = asyncio.Event()
        self._reaper: asyncio.Task | None = None
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise AppError("SERVICE_NOT_READY", "会话服务正在关闭", 503)
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap())

    @staticmethod
    def _document_view(document: SessionDocument) -> DocumentView:
        return DocumentView(
            id=document.id, filename=document.filename, chars=len(document.markdown)
        )

    @staticmethod
    def _message_view(message: SessionMessage) -> MessageView:
        call = (
            AgentCallView(**message.agent_call.model_dump(), status="succeeded")
            if message.agent_call
            else None
        )
        return MessageView(
            id=message.id,
            sequence=message.sequence,
            role=message.role,
            content=message.content,
            document_ids=list(message.document_ids),
            run_id=message.run_id,
            agent_call=call,
        )

    def _run_view(self, run: SessionRun) -> RunView:
        return RunView(
            id=run.id,
            client_message_id=run.request.client_message_id,
            status=run.status,
            stage=run.stage,
            message=self._message_view(run.message) if run.message else None,
            error=SafeError(code=run.error_code, message=run.error_message)
            if run.error_code
            else None,
        )

    async def create(self) -> ConversationView:
        self._check_open()
        return await self.read(self._store.create().id)

    async def read(self, id: str, *, after_sequence: int = 0) -> ConversationView:
        record = self._store.record(id)
        return ConversationView(
            id=id,
            expires_in_seconds=self._store.remaining_seconds(id),
            messages=[
                self._message_view(m) for m in record.messages if m.sequence > after_sequence
            ],
            documents=[self._document_view(d) for d in record.documents.values()],
            active_run_id=record.active_run_id,
            last_sequence=record.messages[-1].sequence if record.messages else 0,
        )

    async def _parse_upload(self, filename: str, content: bytes) -> SessionDocument:
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
        return SessionDocument(id=str(uuid4()), filename=name or "文档.docx", markdown=markdown)

    async def upload(self, id: str, filename: str, content: bytes) -> DocumentView:
        self._check_open()
        async with self._store.locked(id) as record:
            if record.active_run_id or record.uploading:
                raise AppError("CONVERSATION_BUSY", "请等待当前操作完成", 409)
            if len(record.documents) >= 8:
                raise AppError("CONVERSATION_CAPACITY", "每个会话最多上传 8 份材料", 413)
            self._store.reserve(len(content))
            record.uploading = True
            self._uploads[id] = asyncio.current_task()
        try:
            async with self._parse_slots:
                document = await self._parse_upload(filename, content)
            async with self._store.locked(id) as record:
                if (
                    sum(len(d.markdown) for d in record.documents.values()) + len(document.markdown)
                    > 100000
                ):
                    raise AppError("CONVERSATION_CAPACITY", "会话材料正文合计超过限制", 413)
                amount = len(document.markdown.encode("utf-8"))
                self._store.reserve(amount)
                record.bytes_used += amount
                record.documents[document.id] = document
                self._store.touch(id)
                return self._document_view(document)
        finally:
            self._store.release(len(content))
            record = self._store.peek(id)
            if record:
                record.uploading = False
            self._uploads.pop(id, None)

    async def submit(self, id: str, payload: MessageCreate) -> RunView:
        self._check_open()
        if self.runtime is None:
            raise AppError("SERVICE_NOT_READY", "聊天模型尚未配置就绪", 503)
        request = SessionSubmission(
            payload.client_message_id,
            payload.content,
            tuple(payload.document_ids),
        )
        async with self._store.locked(id) as record:
            for run in record.runs.values():
                if run.request.client_message_id == payload.client_message_id:
                    if run.request != request:
                        raise AppError("MESSAGE_CONFLICT", "消息标识已用于其他内容", 409)
                    return self._run_view(run)
            if record.active_run_id or record.uploading:
                raise AppError("CONVERSATION_BUSY", "请等待当前操作完成", 409)
            if len(record.messages) > 98:
                raise AppError("CONVERSATION_CAPACITY", "本会话消息已满，请新建会话", 413)
            if any(doc_id not in record.documents for doc_id in payload.document_ids):
                raise AppError("MATERIAL_NOT_FOUND", "会话材料不存在", 404)
            if (
                len(self._tasks)
                >= self.settings.conversation_concurrency + self.settings.conversation_queue_size
            ):
                raise AppError("CONVERSATION_BUSY", "会话执行繁忙，请稍后重试", 503)
            chars = sum(
                len(m.content) + (len(m.agent_call.output) if m.agent_call else 0)
                for m in record.messages
            )
            if chars + len(payload.content) > 1000000:
                raise AppError("CONVERSATION_CAPACITY", "会话文字容量已满", 413)
            amount = len(payload.content.encode("utf-8")) + 1024
            self._store.reserve(amount)
            record.bytes_used += amount
            run = SessionRun(id=str(uuid4()), request=request)
            record.messages.append(
                SessionMessage(
                    id=str(uuid4()),
                    sequence=len(record.messages) + 1,
                    role="user",
                    content=payload.content,
                    document_ids=tuple(payload.document_ids),
                    run_id=run.id,
                )
            )
            record.runs[run.id] = run
            record.active_run_id = run.id
            self._store.touch(id)
            self._tasks[run.id] = asyncio.create_task(self._execute(id, run.id))
            return self._run_view(run)

    async def read_run(self, id: str, run_id: str) -> RunView:
        run = self._store.record(id).runs.get(run_id)
        if run is None:
            raise AppError("RUN_NOT_FOUND", "会话运行不存在", 404)
        return self._run_view(run)

    async def cancel(self, id: str, run_id: str) -> RunView:
        run = await self.read_run(id, run_id)
        if run.status not in TERMINAL_STATUSES:
            task = self._tasks.get(run_id)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self._finish(id, run_id, "cancelled", "已停止。")
            self._tasks.pop(run_id, None)
        return await self.read_run(id, run_id)

    def _finish(
        self,
        id: str,
        run_id: str,
        status: str,
        text: str,
        *,
        call: ChildAgentResult | None = None,
        error: SafeError | None = None,
        continuation: ContinuationState | None = None,
    ) -> None:
        record = self._store.peek(id)
        if record is None:
            return
        run = record.runs[run_id]
        if run.status in TERMINAL_STATUSES:
            return
        amount = len(text.encode("utf-8")) + (len(call.output.encode("utf-8")) if call else 0)
        total_chars = (
            sum(
                len(m.content) + (len(m.agent_call.output) if m.agent_call else 0)
                for m in record.messages
            )
            + len(text)
            + (len(call.output) if call else 0)
        )
        try:
            if total_chars > 1000000:
                raise AppError("CONVERSATION_CAPACITY", "会话输出超过容量限制", 413)
            self._store.reserve(max(0, amount - 1024))
        except AppError as exc:
            status, text, call, continuation = "failed", exc.message, None, None
            error = SafeError(code=exc.code, message=exc.message)
            amount = len(text.encode("utf-8"))
        if amount < 1024:
            self._store.release(1024 - amount)
        record.bytes_used += amount - 1024
        message = SessionMessage(
            id=str(uuid4()),
            sequence=len(record.messages) + 1,
            role="assistant",
            content=text,
            run_id=run_id,
            agent_call=call,
        )
        record.messages.append(message)
        run.status, run.stage, run.message = (
            status,
            text if status != "succeeded" else "已完成",
            message,
        )
        run.error_code = error.code if error else None
        run.error_message = error.message if error else None
        record.active_run_id = None
        record.continuation = (
            continuation.model_copy(deep=True, update={"question_message_id": message.id})
            if continuation
            else None
        )

    async def _execute(self, id: str, run_id: str) -> None:
        acquired = False
        try:
            async with asyncio.timeout(self.settings.conversation_queue_timeout_seconds):
                await self._slots.acquire()
                acquired = True
            async with asyncio.timeout(self.settings.conversation_run_timeout_seconds):
                record = self._store.record(id)
                run = record.runs[run_id]
                run.status, run.stage = "running", "正在处理你的请求"
                snapshot = self._store.snapshot(record)
                turn = ConversationTurnInput(
                    latest_message_id=snapshot.latest_message_id,
                    messages=tuple(
                        TurnMessage.model_validate(
                            m.model_dump(
                                exclude={"sequence", "run_id"},
                            )
                        )
                        for m in snapshot.messages
                    ),
                    documents=tuple(
                        TurnDocument.model_validate(d.model_dump())
                        for d in snapshot.documents.values()
                    ),
                    continuation=snapshot.continuation,
                )
                execution = await self.runtime.invoke("conversation_assistant", turn.model_dump())
                if asyncio.current_task().cancelling():
                    raise asyncio.CancelledError
                result = ConversationTurnResult.model_validate(execution.output)
                self._finish(
                    id,
                    run_id,
                    "succeeded",
                    result.reply,
                    call=result.child_call,
                    continuation=result.continuation,
                )
        except asyncio.CancelledError:
            self._finish(id, run_id, "cancelled", "已停止。")
            raise
        except TimeoutError:
            self._finish(
                id,
                run_id,
                "failed",
                "处理超时，请稍后重新提交。",
                error=SafeError(code="CONVERSATION_TIMEOUT", message="处理超时"),
            )
        except Exception as exc:
            code = exc.code if isinstance(exc, AppError) else "CONVERSATION_FAILED"
            message = exc.message if isinstance(exc, AppError) else "本次处理失败，请稍后重试。"
            logger.warning(
                "conversation_failed run_id=%s code=%s error_type=%s",
                run_id,
                code,
                type(exc).__name__,
            )
            self._finish(id, run_id, "failed", message, error=SafeError(code=code, message=message))
        finally:
            if acquired:
                self._slots.release()
            self._tasks.pop(run_id, None)

    async def _reap(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except TimeoutError:
                await self._expire_sessions()

    async def _expire_sessions(self) -> None:
        for id in self._store.expire():
            record = self._store.peek(id)
            if record and record.active_run_id:
                run_id = record.active_run_id
                task = self._tasks.get(run_id)
                if task:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                self._finish(id, run_id, "cancelled", "会话已到期。")
            upload = self._uploads.get(id)
            if upload:
                upload.cancel()
                await asyncio.gather(upload, return_exceptions=True)
        self._store.expire()

    async def aclose(self) -> None:
        self._closed = True
        self._stop.set()
        tasks = list(self._tasks.values()) + list(self._uploads.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._reaper:
            await self._reaper
        self._tasks.clear()
        self._uploads.clear()
        self._store.clear()
