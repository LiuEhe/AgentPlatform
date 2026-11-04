import asyncio
from types import SimpleNamespace

import pytest
from conftest import runtime_result
from pydantic import SecretStr
from test_observability_runtime import RecordingObserver

from app.core.config import Settings
from app.core.observability import bind_observation_attributes
from app.infrastructure.conversation.active_runs import ActiveRunRegistry
from app.infrastructure.conversation.checkpoints import CheckpointResources
from app.infrastructure.conversation.postgres_store import PostgresConversationStore
from app.infrastructure.database import Database
from app.schemas.conversation import MessageCreate
from app.services.conversation_service import ConversationService

POSTGRES_TARGET = ("", "")


@pytest.fixture(autouse=True)
def service_target(postgres_target, monkeypatch):
    monkeypatch.setitem(globals(), "POSTGRES_TARGET", postgres_target)


async def build_service():
    class Runtime:
        async def invoke(self, agent_id, payload, *, on_event=None, resources=None):
            return SimpleNamespace(output=runtime_result(payload, "ok"))

    dsn, schema = POSTGRES_TARGET
    settings = Settings(_env_file=None, database_url=SecretStr(dsn))
    store = PostgresConversationStore(Database(settings , schema=schema))
    await store.database.initialize()
    checkpoints = CheckpointResources(settings, schema=schema)
    await checkpoints.open()
    observer = RecordingObserver()
    service = ConversationService(
        settings,
        Runtime(),
        store=store,
        checkpoints=checkpoints,
        active_runs=ActiveRunRegistry(max_bytes=100000),
        observer=observer,
    )
    return service, observer


def test_run_has_new_root_after_202_and_preserves_request_id(actor):
    async def run():
        service, observer = await build_service()
        session = await service.create(actor)
        with bind_observation_attributes({"request_id": "request-1"}):
            result = await service.submit(actor,
                session.session_id, MessageCreate(client_message_id="x", content="hi")
            )
        task = service._tasks[result.run_id]
        await task
        roots = [r for r in observer.records if r["name"] == "conversation.run"]
        assert len(roots) == 1 and roots[0]["parent"] is None
        assert roots[0]["request_id"] == "request-1"
        assert roots[0]["session_id"] == session.session_id
        await service.aclose()
        await service._checkpoints.aclose()
        await service._store.database.aclose()

    asyncio.run(run())


def test_idempotent_submit_creates_one_run_trace(actor):
    async def run():
        service, observer = await build_service()
        session = await service.create(actor)
        message = MessageCreate(client_message_id="x", content="hi")
        first = await service.submit(actor, session.session_id, message)
        second = await service.submit(actor, session.session_id, message)
        assert first.run_id == second.run_id
        await asyncio.gather(*list(service._tasks.values()))
        assert len(observer.records) == 1
        await service.aclose()
        await service._store.database.aclose()

    asyncio.run(run())


def test_cancel_while_queued_finishes_observation(actor):
    async def run():
        service, observer = await build_service()
        for _ in range(service.settings.conversation_concurrency):
            await service._slots.acquire()
        session = await service.create(actor)
        result = await service.submit(actor,
            session.session_id, MessageCreate(client_message_id="x", content="hi")
        )
        task = service._tasks[result.run_id]
        await asyncio.sleep(0)
        await service.cancel(actor, session.session_id, result.run_id)
        await asyncio.gather(task, return_exceptions=True)
        assert observer.records[0]["attributes"]["status"] == "cancelled"
        assert result.run_id not in service._tasks
        await service.aclose()
        await service._store.database.aclose()

    asyncio.run(run())
