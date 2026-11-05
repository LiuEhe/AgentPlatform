"""本人资料和管理员账号管理用例。"""

import asyncio
import logging
from contextlib import asynccontextmanager

from app.core.errors import AppError
from app.schemas.identity import AvatarWriteState

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, store, passwords, avatars):
        self.store, self.passwords = store, passwords
        self.avatars = avatars
        self._avatar_slots = asyncio.Semaphore(2)
        self._avatar_tasks = set()
        self._closing = False

    @asynccontextmanager
    async def avatar_upload_slot(self):
        if self._closing:
            raise AppError("AVATAR_UNAVAILABLE", "头像服务正在关闭", 503)
        if self._avatar_slots.locked():
            raise AppError("AVATAR_BUSY", "头像正在处理中，请稍后重试", 429)
        await self._avatar_slots.acquire()
        try:
            yield
        finally:
            self._avatar_slots.release()

    def _start_file_work(self, function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        self._avatar_tasks.add(task)
        task.add_done_callback(self._avatar_tasks.discard)
        return task

    @staticmethod
    async def _settle(task):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        return task.result()

    async def _file_work(self, function, *args):
        task = self._start_file_work(function, *args)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await self._settle(task)
            except Exception:
                pass
            raise

    async def _discard_avatar(self, path):
        if path:
            try:
                await self._file_work(self.avatars.discard, path)
            except (AppError, OSError):
                logger.warning("identity_event operation=avatar_cleanup_failed")

    async def upload_avatar(self, actor, filename, content):
        path = None
        state = AvatarWriteState()
        worker = self._start_file_work(self.avatars.publish, actor.user.user_id, filename, content)
        try:
            try:
                path = await asyncio.shield(worker)
            except asyncio.CancelledError:
                try:
                    path = await self._settle(worker)
                except Exception:
                    pass
                raise
            result = await self.store.replace_avatar(actor, path, state=state)
        except BaseException:
            if path and not state.commit_started:
                await self._discard_avatar(path)
            raise
        await self._discard_avatar(result.previous_path)
        return result.profile

    async def remove_avatar(self, actor):
        result = await self.store.replace_avatar(actor, None, state=AvatarWriteState())
        await self._discard_avatar(result.previous_path)

    async def read_avatar(self, actor, *, target_user_id=None):
        path = await self.store.read_avatar_path(actor, target_user_id=target_user_id)
        if path is None:
            raise AppError("AVATAR_NOT_FOUND", "尚未设置头像", 404)
        return await self._file_work(self.avatars.read, path)

    async def aclose(self):
        self._closing = True
        if self._avatar_tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(self._avatar_tasks)),
                                 return_exceptions=True)

    async def read_profile(self, actor, *, target_user_id=None):
        return await self.store.read_profile(actor, target_user_id=target_user_id)

    async def update_profile(self, actor, changes):
        return await self.store.update_profile(actor, changes.model_dump(exclude_unset=True))

    async def create_user(self, actor, username, display_name, temporary_password):
        user = await self.store.create_user(
            actor, username, display_name, await self.passwords.hash(temporary_password),
        )
        logger.info("identity_event operation=create_user actor=%s target=%s",
                    actor.user.user_id, user.user_id)
        return user

    async def set_status(self, actor, target_user_id, status):
        user = await self.store.set_status(actor, target_user_id, status)
        logger.info("identity_event operation=set_status actor=%s target=%s status=%s",
                    actor.user.user_id, target_user_id, status)
        return user

    async def reset_password(self, actor, target_user_id, temporary_password):
        await self.store.reset_password(
            actor, target_user_id, await self.passwords.hash(temporary_password),
        )
        logger.info("identity_event operation=password_reset actor=%s target=%s",
                    actor.user.user_id, target_user_id)

    async def list_users(self, actor, *, limit=20, cursor=None):
        return await self.store.list_users(actor, limit=limit, cursor=cursor)
