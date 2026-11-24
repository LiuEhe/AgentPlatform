"""接收、解析并持久化会话附件。"""

import asyncio
import logging
from pathlib import PurePath
from uuid import uuid4

from app.core.errors import AppError
from app.nodes.document.parse import DocumentParseError, parse_docx
from app.schemas.conversation_session import SessionFile
from app.schemas.conversation_turn import TurnDocument

logger = logging.getLogger(__name__)


class ConversationUploadService:
    def __init__(self, settings, *, store, active_runs, files, check_open):
        self.settings = settings
        self._store, self._active = store, active_runs
        self._files = files
        self._check_open = check_open
        self._parse_slots = asyncio.Semaphore(2)
        self._uploads: dict[str, asyncio.Task] = {}

    def in_progress(self, session_id: str) -> bool:
        return session_id in self._uploads

    def pending_tasks(self) -> tuple[asyncio.Task, ...]:
        return tuple(self._uploads.values())

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
                        await asyncio.wait((task,))
                    except asyncio.CancelledError:
                        continue
                if not task.cancelled():
                    task.exception()
                raise
        except DocumentParseError as exc:
            status = 413 if exc.code in {"UPLOAD_TOO_LARGE", "REVIEW_CONTENT_TOO_LONG"} else 422
            raise AppError(exc.code, exc.message, status) from exc
        name = " ".join(filename.replace("\\", "/").split("/")[-1].split())[:200]
        return TurnDocument(id=str(uuid4()), filename=name or "文档.docx", markdown=markdown)

    async def upload(self, actor, session_id: str, filename: str, content: bytes):
        await self._store.authorize(actor, session_id)
        self._check_open()
        async with self._active.operation(session_id):
            self._check_open()
            if self.in_progress(session_id):
                raise AppError("CONVERSATION_BUSY", "请等待当前上传完成", 409)
            self._active.reserve(len(content))
            self._uploads[session_id] = asyncio.current_task()
        try:
            page = await self._store.read(actor, session_id)
            self._check_open()
            if page.active_run_id:
                raise AppError("CONVERSATION_BUSY", "请等待当前操作完成", 409)
            cancelled = asyncio.Event()
            task = asyncio.create_task(
                self._save_upload(actor, session_id, page, filename, content, cancelled)
            )
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled.set()
                # 文件写入与解析线程无法强制终止，反复取消也必须等待清理结束。
                while not task.done():
                    try:
                        await asyncio.wait((task,))
                    except asyncio.CancelledError:
                        continue
                if not task.cancelled():
                    task.exception()
                raise
        finally:
            self._active.release(len(content))
            self._uploads.pop(session_id, None)

    async def _save_upload(self, actor, session_id, page, filename, content, cancelled):
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
                saved = await self._store.add_file(actor, session_id, metadata)
                confirmed = True
                return saved
        finally:
            if paths and not confirmed:
                try:
                    await self._store.get_file(actor.user.user_id, session_id, document.id)
                except AppError as exc:
                    if exc.code == "MATERIAL_NOT_FOUND":
                        await asyncio.to_thread(self._files.discard_published, paths)
                    else:
                        logger.warning("upload_commit_unconfirmed file_id=%s", document.id)
                except Exception as exc:
                    # An unknown commit outcome must keep the published file.
                    logger.warning(
                        "upload_commit_unconfirmed file_id=%s error_type=%s",
                        document.id, type(exc).__name__,
                    )
            if staged:
                await asyncio.to_thread(self._files.discard_staged, staged)
