"""单进程临时会话存储；不解释 Agent 业务，也不返回 HTTP View。"""

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from time import monotonic
from uuid import uuid4

from app.core.errors import AppError
from app.schemas.conversation_session import ConversationSession, SessionSnapshot


class InMemoryConversationStore:
    def __init__(
        self,
        *,
        idle_seconds: float,
        lifetime_seconds: float,
        max_sessions: int,
        max_bytes: int,
        clock: Callable[[], float] = monotonic,
    ):
        self._idle_seconds = idle_seconds
        self._lifetime_seconds = lifetime_seconds
        self._max_sessions = max_sessions
        self._max_bytes = max_bytes
        self._clock = clock
        self._records: dict[str, ConversationSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._used_bytes = 0

    @property
    def used_bytes(self) -> int:
        return self._used_bytes

    def reserve(self, amount: int) -> None:
        if amount < 0 or self._used_bytes + amount > self._max_bytes:
            raise AppError("CONVERSATION_CAPACITY", "会话容量已满，请稍后重试", 413)
        self._used_bytes += amount

    def release(self, amount: int) -> None:
        self._used_bytes = max(0, self._used_bytes - amount)

    def create(self) -> ConversationSession:
        self.expire()
        if len(self._records) >= self._max_sessions:
            raise AppError("CONVERSATION_CAPACITY", "临时会话数量已满", 503)
        now = self._clock()
        session = ConversationSession(str(uuid4()), now, now)
        self._records[session.id] = session
        self._locks[session.id] = asyncio.Lock()
        return session

    def _due(self, record: ConversationSession) -> bool:
        now = self._clock()
        return now - record.created >= self._lifetime_seconds or (
            not record.active_run_id
            and not record.uploading
            and now - record.interacted >= self._idle_seconds
        )

    def record(self, id: str) -> ConversationSession:
        record = self.peek(id)
        if record is None or self._due(record):
            raise AppError("CONVERSATION_NOT_FOUND", "会话已失效，请新建会话", 404)
        return record

    def peek(self, id: str) -> ConversationSession | None:
        """仅供生命周期收尾；允许取得尚未释放的过期记录。"""
        return self._records.get(id)

    def touch(self, id: str) -> None:
        self.record(id).interacted = self._clock()

    def remaining_seconds(self, id: str) -> int:
        record = self.record(id)
        now = self._clock()
        remaining = min(
            self._lifetime_seconds - (now - record.created),
            self._idle_seconds - (now - record.interacted),
        )
        return max(0, int(remaining))

    @asynccontextmanager
    async def locked(self, id: str):
        self.record(id)
        async with self._locks[id]:
            yield self.record(id)

    def snapshot(self, record: ConversationSession) -> SessionSnapshot:
        return SessionSnapshot(
            record.id,
            record.messages[-1].id,
            deepcopy(tuple(record.messages)),
            deepcopy(record.documents),
            deepcopy(record.continuation),
        )

    def expire(self) -> list[str]:
        expired = [id for id, record in self._records.items() if self._due(record)]
        for id in expired:
            record = self._records[id]
            if not record.active_run_id and not record.uploading:
                self.release(record.bytes_used)
                del self._records[id]
                self._locks.pop(id, None)
        return expired

    def clear(self) -> None:
        self._records.clear()
        self._locks.clear()
        self._used_bytes = 0
