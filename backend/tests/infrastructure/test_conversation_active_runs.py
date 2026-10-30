import asyncio

import pytest

from app.core.errors import AppError
from app.infrastructure.conversation.active_runs import ActiveRunRegistry
from app.schemas.conversation_session import SessionRun, SessionSubmission


def test_terminal_releases_utf8_bytes_and_wakes_subscriber():
    async def scenario():
        registry = ActiveRunRegistry(max_bytes=64)
        run = SessionRun(run_id="r", request=SessionSubmission("m", "hi"))
        registry.attach("c", run)
        state = registry.snapshot("r")
        registry.append_text("r", "你好")
        assert registry.used_bytes == 6
        await asyncio.wait_for(registry.wait_changed("r", state.revision), 1)
        assert registry.snapshot("r").text == "你好"
        run.status = "succeeded"
        registry.complete("r", run)
        assert registry.used_bytes == 0
        assert registry.snapshot("r").run.status == "succeeded"

    asyncio.run(scenario())


def test_capacity_failure_and_unavailable_wake_readers():
    async def scenario():
        registry = ActiveRunRegistry(max_bytes=5)
        registry.attach("c", SessionRun(run_id="r", request=SessionSubmission("m", "hi")))
        with pytest.raises(AppError):
            registry.append_text("r", "你好")
        registry.fail_unavailable()
        await asyncio.wait_for(registry.wait_changed("r", 0), 1)
        assert registry.snapshot("r").unavailable
        assert registry.used_bytes == 0
        for _ in range(3):
            async with registry.operation("c"):
                pass
        assert not registry._locks

    asyncio.run(scenario())
