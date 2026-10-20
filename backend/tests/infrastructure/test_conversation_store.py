import asyncio

import pytest

from app.core.errors import AppError
from app.infrastructure.conversation.in_memory_store import InMemoryConversationStore
from app.schemas.conversation_session import SessionMessage
from app.schemas.conversation_turn import ContinuationState


def store(*, clock=lambda: 0.0, max_bytes=1000):
    return InMemoryConversationStore(
        idle_seconds=7200,
        lifetime_seconds=28800,
        max_sessions=100,
        max_bytes=max_bytes,
        clock=clock,
    )


def test_store_isolates_sessions():
    memory = store()
    a, b = memory.create(), memory.create()
    assert a.id != b.id and a.messages == b.messages == []
    a.messages.append(SessionMessage(id="m", sequence=1, role="user", content="正文"))
    assert b.messages == []


def test_poll_does_not_refresh_ttl():
    now = [0.0]
    memory = store(clock=lambda: now[0])
    session = memory.create()
    now[0] = 7100
    assert memory.record(session.id).id == session.id
    assert memory.remaining_seconds(session.id) == 100
    now[0] = 7201
    with pytest.raises(AppError, match="会话"):
        memory.record(session.id)


def test_touch_refreshes_real_interaction():
    now = [0.0]
    memory = store(clock=lambda: now[0])
    session = memory.create()
    now[0] = 7100
    memory.touch(session.id)
    now[0] = 7201
    assert memory.remaining_seconds(session.id) == 7099


def test_snapshot_is_detached():
    memory = store()
    session = memory.create()
    session.messages.append(SessionMessage(id="m", sequence=1, role="user", content="正文"))
    session.continuation = ContinuationState(payload={"nested": {"value": 1}})
    snapshot = memory.snapshot(session)
    snapshot.messages[0].content = "修改"
    snapshot.continuation.payload["nested"]["value"] = 2
    assert session.messages[0].content == "正文"
    assert session.continuation.payload["nested"]["value"] == 1


def test_capacity_reservation_rolls_back():
    memory = store(max_bytes=16)
    memory.reserve(16)
    with pytest.raises(AppError):
        memory.reserve(1)
    assert memory.used_bytes == 16
    memory.release(16)
    memory.reserve(16)
    assert memory.used_bytes == 16


def test_active_expired_session_is_reported_before_removal():
    now = [0.0]
    memory = store(clock=lambda: now[0])
    session = memory.create()
    memory.reserve(20)
    session.bytes_used = 20
    session.active_run_id = "r"
    now[0] = 28801
    assert memory.expire() == [session.id]
    with pytest.raises(AppError):
        memory.record(session.id)
    assert memory.peek(session.id) is session
    assert memory.used_bytes == 20
    session.active_run_id = None
    memory.expire()
    assert memory.peek(session.id) is None and memory.used_bytes == 0


def test_locks_are_per_session():
    async def scenario():
        memory = store()
        a, b = memory.create(), memory.create()
        async with memory.locked(a.id):
            async with memory.locked(b.id) as record:
                assert record is b
        memory.clear()
        assert memory.peek(a.id) is None and memory.used_bytes == 0

    asyncio.run(scenario())
