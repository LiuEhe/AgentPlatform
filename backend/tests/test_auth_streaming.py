import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.auth import guard_run_events
from app.core.errors import AppError


@pytest.mark.parametrize("failure", ["AUTH_REQUIRED", "STORAGE_UNAVAILABLE"])
def test_idle_subscription_rechecks_and_closes_without_fake_done(monkeypatch, failure):
    async def scenario():
        checks = 0
        closed = False
        observed = []
        original_wait = asyncio.wait

        async def bounded_wait(tasks, *, timeout):
            assert 0 < timeout <= 5
            return await original_wait(tasks, timeout=.01)

        monkeypatch.setattr("app.api.auth.asyncio.wait", bounded_wait)

        async def live(context):
            nonlocal checks
            checks += 1
            if checks > 1:
                raise AppError(failure, "closed", 401 if failure == "AUTH_REQUIRED" else 503)

        async def events():
            nonlocal closed
            try:
                await asyncio.Event().wait()
                yield "unreachable"
            finally:
                closed = True

        context = SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(hours=1))
        async for event in guard_run_events(context, events(), assert_live=live):
            observed.append(event)
        assert checks == 2 and closed and observed == []

    asyncio.run(scenario())


def test_frame_is_reauthorized_before_it_is_delivered():
    async def scenario():
        checks = 0
        async def live(context):
            nonlocal checks
            checks += 1
            if checks == 2:
                raise AppError("AUTH_REQUIRED", "revoked", 401)
        async def events():
            yield "private frame"
        context = SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(hours=1))
        assert [
            event async for event in guard_run_events(context, events(), assert_live=live)
        ] == []

    asyncio.run(scenario())
