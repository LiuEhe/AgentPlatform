"""进程内活动任务通知和有界流式文本，不存持久历史。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace

from app.core.errors import AppError
from app.schemas.conversation_session import SessionRun


@dataclass
class ActiveRun:
    run: SessionRun
    stage: str = "等待处理"
    text: str = ""
    revision: int = 0
    unavailable: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def notify(self):
        self.revision += 1
        self.changed.set()


class ActiveRunRegistry:
    def __init__(self, *, max_bytes: int):
        self.max_bytes = max_bytes
        self.used_bytes = 0
        self._runs: dict[str, ActiveRun] = {}
        self._locks: dict[str, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def operation(self, session_id: str) -> AsyncIterator[None]:
        lock, users = self._locks.get(session_id, (asyncio.Lock(), 0))
        self._locks[session_id] = lock, users + 1
        try:
            async with lock:
                yield
        finally:
            _, users = self._locks[session_id]
            if users == 1:
                del self._locks[session_id]
            else:
                self._locks[session_id] = lock, users - 1

    def reserve(self, amount: int):
        if amount < 0 or self.used_bytes + amount > self.max_bytes:
            raise AppError("CONVERSATION_CAPACITY", "临时会话资源已满，请稍后重试", 413)
        self.used_bytes += amount

    def release(self, amount: int):
        self.used_bytes = max(0, self.used_bytes - amount)

    def attach(self, session_id: str, run: SessionRun):
        self._runs[run.run_id] = ActiveRun(run=run, stage=run.stage)

    def snapshot(self, run_id: str) -> ActiveRun | None:
        state = self._runs.get(run_id)
        return replace(state) if state else None

    def subscribe(self, run_id: str) -> ActiveRun | None:
        """订阅持有通知对象；终态移出索引后既有订阅仍可读取已提交结果。"""
        return self._runs.get(run_id)

    def append_text(self, run_id: str, text: str):
        state = self._runs[run_id]
        if state.unavailable:
            raise AppError("STORAGE_UNAVAILABLE", "历史保存服务不可用", 503)
        if state.run.status not in {"queued", "running"}:
            return
        if len(state.text) + len(text) > 200000:
            raise AppError("CONVERSATION_CAPACITY", "会话回答超过长度限制", 413)
        self.reserve(len(text.encode("utf-8")))
        state.text += text
        state.notify()

    def set_stage(self, run_id: str, stage: str):
        state = self._runs[run_id]
        state.stage = stage
        state.notify()

    def update_run(self, run: SessionRun):
        self._runs[run.run_id].run = run
        self._runs[run.run_id].notify()

    async def wait_changed(self, run_id: str, revision: int):
        state = self._runs.get(run_id)
        if state is None:
            return
        state.changed.clear()
        if state.revision == revision:
            await state.changed.wait()

    def complete(self, run_id: str, committed_run: SessionRun):
        state = self._runs.get(run_id)
        if state:
            self.release(len(state.text.encode("utf-8")))
            state.text = ""
            state.run = committed_run
            state.stage = committed_run.stage
            state.notify()

    def discard(self, run_id: str):
        state = self._runs.pop(run_id, None)
        if state:
            self.release(len(state.text.encode("utf-8")))
            state.notify()

    def fail_unavailable(self):
        for state in self._runs.values():
            state.unavailable = True
            self.release(len(state.text.encode("utf-8")))
            state.text = ""
            state.notify()

    async def aclose(self):
        self.fail_unavailable()
        self._runs.clear()
