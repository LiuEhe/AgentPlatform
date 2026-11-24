"""协调会话删除、清理凭据及重启恢复。"""

import asyncio
import logging
from uuid import UUID

from app.core.errors import AppError
from app.schemas.conversation_turn import conversation_thread_id

logger = logging.getLogger(__name__)


class ConversationDeletionService:
    def __init__(
        self, *, store, active_runs, files, checkpoints, check_open, upload_pending, run_pending,
    ):
        self._store, self._active = store, active_runs
        self._files, self._checkpoints = files, checkpoints
        self._check_open = check_open
        self._upload_pending = upload_pending
        self._run_pending = run_pending
        self._deletion_tasks: dict[str, asyncio.Task[None]] = {}

    async def wait_for_pending(self) -> None:
        await asyncio.gather(*self._deletion_tasks.values(), return_exceptions=True)

    async def delete(self, actor, session_id: str) -> None:
        self._check_open()
        try:
            session_id = str(UUID(session_id))
        except (ValueError, TypeError, AttributeError):
            raise AppError("CONVERSATION_NOT_FOUND", "会话不存在", 404) from None
        await self._store.authorize(actor, session_id, optional=True)
        intent = await asyncio.to_thread(self._files.read_deletion_intent, session_id)
        if intent is not None and intent.user_id != str(actor.user.user_id):
            raise AppError("CONVERSATION_NOT_FOUND", "会话不存在", 404)
        self._check_open()
        task = self._deletion_tasks.get(session_id)
        if task is None or task.done():
            task = asyncio.create_task(self._delete_session(actor, session_id))
            self._deletion_tasks[session_id] = task
            def finished(done):
                if self._deletion_tasks.get(session_id) is done:
                    self._deletion_tasks.pop(session_id, None)
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
        await asyncio.shield(task)

    async def _delete_session(self, actor, session_id: str) -> None:
        async with self._active.operation(session_id):
            if self._upload_pending(session_id):
                raise AppError("CONVERSATION_BUSY", "请等待当前上传结束后再删除", 409)
            target = await self._store.inspect_deletion(actor, session_id)
            if target:
                if target.active_run_id or any(self._run_pending(key) for key in target.run_ids):
                    raise AppError("CONVERSATION_BUSY", "请等待当前操作结束后再删除", 409)
                try:
                    intent = await asyncio.to_thread(
                        self._files.write_deletion_intent,
                        target.agent_id,
                        session_id,
                        str(actor.user.user_id),
                    )
                except (AppError, OSError):
                    raise AppError("STORAGE_UNAVAILABLE", "无法准备删除，请稍后重试", 503) from None
                try:
                    await self._store.delete_session(actor, session_id)
                except Exception as failure:
                    # 新事务等待原写入结束；查询失败时保留凭据，绝不据超时清理文件。
                    remaining = await self._store.inspect_deletion(actor, session_id)
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
                if intent.user_id != str(actor.user.user_id):
                    raise AppError("CONVERSATION_NOT_FOUND", "会话不存在", 404)
            try:
                await self._checkpoints.delete_thread(
                    conversation_thread_id(intent.agent_id, session_id),
                )
                await asyncio.to_thread(self._files.discard_session, intent.agent_id, session_id)
                await asyncio.to_thread(self._files.discard_deletion_intent, session_id)
            except (AppError, OSError):
                raise AppError(
                    "CONVERSATION_DELETE_INCOMPLETE",
                    "对话已删除，记忆或附件清理未完成，请重试清理",
                    503,
                ) from None

    async def recover_deletions(self) -> None:
        try:
            intents = await asyncio.to_thread(self._files.list_deletion_intents)
        except (AppError, OSError):
            raise AppError(
                "STORAGE_SCHEMA_INVALID", "删除凭据格式无效，请离线核实并修复", 503,
            ) from None
        for intent in intents:
            try:
                async with self._active.operation(intent.session_id):
                    target = await self._store.inspect_deletion(
                        UUID(intent.user_id), intent.session_id
                    )
                    if target is None:
                        await self._checkpoints.delete_thread(
                            conversation_thread_id(intent.agent_id, intent.session_id),
                        )
                        await asyncio.to_thread(
                            self._files.discard_session, intent.agent_id, intent.session_id
                        )
                    await asyncio.to_thread(self._files.discard_deletion_intent, intent.session_id)
            except (AppError, OSError) as exc:
                logger.warning(
                    "deletion_recovery_pending session_id=%s error_type=%s",
                    intent.session_id, type(exc).__name__,
                )
