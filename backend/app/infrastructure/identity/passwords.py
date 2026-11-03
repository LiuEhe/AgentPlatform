"""官方Argon2适配与同进程有界计算。"""

import asyncio

from pwdlib import PasswordHash

from app.core.errors import AppError
from app.schemas.identity import HashVerification, validate_password


class PasswordHasher:
    def __init__(self, *, concurrency=2, queue_size=8, queue_timeout=5):
        self._hash = PasswordHash.recommended()
        self._slots = asyncio.Semaphore(concurrency)
        self._queue_size, self._timeout = queue_size, queue_timeout
        self._waiting = 0
        self._tasks = set()
        self._closed = False

    @staticmethod
    def _busy():
        return AppError("AUTH_BUSY", "密码处理繁忙，请稍后重试", 429, retry_after_seconds=1)

    async def _run(self, operation):
        if self._closed or (self._slots.locked() and self._waiting >= self._queue_size):
            raise self._busy()
        self._waiting += 1
        try:
            try:
                await asyncio.wait_for(self._slots.acquire(), self._timeout)
            except TimeoutError:
                raise self._busy() from None
        finally:
            self._waiting -= 1
        task = asyncio.create_task(asyncio.to_thread(operation))
        self._tasks.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
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
            self._tasks.discard(task)
            self._slots.release()

    async def hash(self, password):
        try:
            validate_password(password)
        except ValueError as exc:
            raise AppError("PASSWORD_INVALID", str(exc), 422) from None
        return await self._run(lambda: self._hash.hash(password))

    async def verify(self, password, encoded_hash):
        valid, replacement = await self._run(
            lambda: self._hash.verify_and_update(password, encoded_hash),
        )
        return HashVerification(valid, replacement)

    async def aclose(self):
        self._closed = True
        await asyncio.gather(*self._tasks, return_exceptions=True)
