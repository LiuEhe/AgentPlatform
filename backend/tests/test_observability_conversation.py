import asyncio
from types import SimpleNamespace

from test_observability_runtime import RecordingObserver

from app.core.config import Settings
from app.core.observability import bind_observation_attributes
from app.infrastructure.conversation.in_memory_store import InMemoryConversationStore
from app.schemas.conversation import MessageCreate
from app.services.conversation_service import ConversationService


def build_service():
    class Runtime:
        async def invoke(self, agent_id, payload, *, on_event=None):
            return SimpleNamespace(output={"reply": "ok"})

    store = InMemoryConversationStore(
        idle_seconds=7200, lifetime_seconds=28800, max_sessions=5, max_bytes=100000
    )
    observer = RecordingObserver()
    service = ConversationService(
        Settings(_env_file=None), Runtime(), store=store, observer=observer
    )
    return service, observer


def test_run_has_new_root_after_202_and_preserves_request_id():
    async def run():
        service, observer = build_service()
        session = await service.create()
        with bind_observation_attributes({"request_id": "request-1"}):
            result = await service.submit(
                session.id, MessageCreate(client_message_id="x", content="hi")
            )
        task = service._tasks[result.id]
        await task
        roots = [r for r in observer.records if r["name"] == "conversation.run"]
        assert len(roots) == 1 and roots[0]["parent"] is None
        assert roots[0]["request_id"] == "request-1"
        assert roots[0]["session_id"] == session.id
        await service.aclose()

    asyncio.run(run())


def test_idempotent_submit_creates_one_run_trace():
    async def run():
        service, observer = build_service()
        session = await service.create()
        message = MessageCreate(client_message_id="x", content="hi")
        first = await service.submit(session.id, message)
        second = await service.submit(session.id, message)
        assert first.id == second.id
        await service._tasks[first.id]
        assert len(observer.records) == 1
        await service.aclose()

    asyncio.run(run())


def test_cancel_while_queued_finishes_observation():
    async def run():
        service, observer = build_service()
        for _ in range(service.settings.conversation_concurrency):
            await service._slots.acquire()
        session = await service.create()
        result = await service.submit(
            session.id, MessageCreate(client_message_id="x", content="hi")
        )
        task = service._tasks[result.id]
        await asyncio.sleep(0)
        await service.cancel(session.id, result.id)
        await asyncio.gather(task, return_exceptions=True)
        assert observer.records[0]["attributes"]["status"] == "cancelled"
        assert result.id not in service._tasks
        await service.aclose()

    asyncio.run(run())
