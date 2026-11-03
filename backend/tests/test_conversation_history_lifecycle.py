import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.conversation.active_runs import ActiveRunRegistry
from app.infrastructure.conversation.postgres_store import PostgresConversationStore
from app.infrastructure.database import Database
from app.main import create_app
from app.schemas.conversation import MessageCreate
from app.schemas.conversation_session import RunCompletion, SessionFile, SessionSubmission
from app.services.conversation_service import ConversationService


def test_startup_recovers_only_admitted_deletions(actor, monkeypatch):
    from uuid import uuid4

    from app.infrastructure.documents.local_file_store import LocalFileStore

    settings = Settings(_env_file=None)
    files = LocalFileStore(settings.documents_root)
    ids = []
    with TestClient(create_app(settings)) as client:
        for _ in range(2):
            sid = client.post("/api/v1/sessions").json()["session_id"]
            files.publish(files.stage("conversation_assistant", sid, str(uuid4()), b"docx", "body"))
            files.write_deletion_intent("conversation_assistant", sid, str(actor.user.user_id))
            client.portal.call(
                client.app.state.conversation_service._store.delete_session, actor, sid
            )
            ids.append(sid)
    original = LocalFileStore.discard_session
    def fail_one(self, agent, sid):
        if sid == ids[0]:
            raise OSError("temporarily unavailable")
        original(self, agent, sid)
    monkeypatch.setattr(LocalFileStore, "discard_session", fail_one)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/sessions").status_code == 200
        assert files.read_deletion_intent(ids[0]) is not None
        assert files.read_deletion_intent(ids[1]) is None


def test_restart_restores_history_and_interrupts_once(actor):
    settings = Settings(_env_file=None)
    with TestClient(create_app(settings)) as client:
        id = client.post("/api/v1/sessions").json()["session_id"]
        store = client.app.state.conversation_service._store
        submitted = client.portal.call(
            store.submit, actor, id, SessionSubmission("queued", "已提交")
        )
    for _ in range(2):
        with TestClient(create_app(settings)) as client:
            history = client.get(f"/api/v1/sessions/{id}").json()
            assert len(history["messages"]) == 2
            assert history["active_run_id"] is None
            result = client.get(f"/api/v1/sessions/{id}/runs/{submitted.run.run_id}").json()
            assert result["status"] == "failed"
            assert result["error"]["code"] == "CONVERSATION_INTERRUPTED"
            assert client.get("/api/v1/sessions").json()["items"][0]["session_id"] == id


def test_pagination_and_invalid_cursor_have_explicit_errors(actor):
    with TestClient(create_app(Settings(_env_file=None))) as client:
        id = client.post("/api/v1/sessions").json()["session_id"]
        store = client.app.state.conversation_service._store
        for i in range(3):
            run = client.portal.call(store.submit, actor, id, SessionSubmission(str(i), f"用户{i}"))
            client.portal.call(
                store.finish, actor, id, run.run.run_id, RunCompletion("succeeded", f"回复{i}")
            )
        page = client.get(f"/api/v1/sessions/{id}?after_sequence=0&limit=2").json()
        assert page["last_sequence"] == 6
        assert page["next_after_sequence"] == 2
        page = client.get(f"/api/v1/sessions/{id}?before_sequence=5&limit=2").json()
        assert [m["sequence"] for m in page["messages"]] == [3, 4]
        assert page["next_before_sequence"] == 3
        assert (
            client.get(f"/api/v1/sessions/{id}?before_sequence=2&after_sequence=0").status_code
            == 422
        )
        assert client.get("/api/v1/sessions?cursor=bad").status_code == 422
        assert client.get(f"/api/v1/sessions/{id}?limit=101").status_code == 422
        assert "expires_in_seconds" not in page


@pytest.mark.parametrize("bad_id", [123, None, ["bad"]])
def test_structurally_invalid_cursor_returns_422(bad_id):
    cursor = base64.urlsafe_b64encode(json.dumps({
        "v": 2, "agent_id": "conversation_assistant", "session_id": bad_id,
        "updated_at": "2026-10-30T00:00:00+00:00",
    }).encode()).decode()
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/api/v1/sessions", params={"cursor": cursor}).status_code == 422


def test_terminal_commit_failure_never_emits_done(actor, postgres_target, monkeypatch):
    from types import SimpleNamespace

    async def scenario():
        dsn, schema = postgres_target
        settings = Settings(_env_file=None, database_url=dsn)
        store = PostgresConversationStore(Database(settings , schema=schema))
        await store.database.initialize()
        gate = asyncio.Event()

        class Runtime:
            calls = 0

            async def invoke(self, *args, **kwargs):
                self.calls += 1
                await gate.wait()
                return SimpleNamespace(output={"reply": "完整但未提交"})

        runtime = Runtime()
        service = ConversationService(
            settings, runtime, store=store, active_runs=ActiveRunRegistry(max_bytes=100000)
        )
        page = await service.create(actor)
        run = await service.submit(actor,
            page.session_id, MessageCreate(client_message_id="m", content="hi")
        )
        reader = await service.stream_run(actor, page.session_id, run.run_id)
        assert (await anext(reader)).event == "snapshot"

        async def fail(*args):
            raise AppError("STORAGE_UNAVAILABLE", "数据库提交失败", 503)

        original = store.finish
        monkeypatch.setattr(store, "finish", fail)
        task = service._tasks[run.run_id]
        gate.set()
        await task
        with pytest.raises(AppError):
            async for event in reader:
                assert event.event != "done"
        assert runtime.calls == 1
        assert (await store.read_run(actor, page.session_id, run.run_id)).status in {
            "queued",
            "running",
        }
        monkeypatch.setattr(store, "finish", original)
        await service.aclose()
        await store.database.initialize()
        assert await store.recover_interrupted() == 1
        assert (
            await store.read_run(actor, page.session_id, run.run_id)
        ).error_code == "CONVERSATION_INTERRUPTED"
        assert await store.recover_interrupted() == 0
        await store.database.aclose()

    asyncio.run(scenario())


def test_exclusive_owner_and_connection_loss(actor, postgres_target):

    async def scenario():
        dsn, schema = postgres_target
        settings = Settings(_env_file=None, database_url=dsn)
        lost = asyncio.Event()
        first = PostgresConversationStore(
            Database(settings, schema=schema, on_unavailable=lost.set)
        )
        second = PostgresConversationStore(Database(settings , schema=schema))
        await first.database.initialize()
        try:
            with pytest.raises(AppError) as raised:
                await second.database.initialize()
            assert raised.value.code == "STORAGE_IN_USE"
            pid = await first.fetchval(
                "SELECT pid FROM pg_locks WHERE locktype='advisory' AND classid=1095782471 AND "
                "objid=1 AND granted"
            )
            try:
                await first.execute("SELECT pg_terminate_backend($1)", pid)
            except AppError:
                pass  # Loss may be observed by the post-commit health check.
            await asyncio.wait_for(lost.wait(), 2)
            with pytest.raises(AppError):
                await first.create(actor)
        finally:
            await first.database.aclose()
            await second.database.aclose()

    asyncio.run(scenario())


def test_foreign_document_and_rolled_back_finish(actor, postgres_target, monkeypatch):
    from uuid import uuid4

    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Database(Settings(_env_file=None, database_url=dsn), schema=schema)
        )
        await store.database.initialize()
        try:
            a, b = await store.create(actor), await store.create(actor)
            doc = SessionFile(
                file_id=str(uuid4()),
                session_id=a.summary.session_id,
                original_name="材料.docx",
                source_path="source.docx",
                content_path="content.md",
                size_bytes=10,
                content_chars=4,
            )
            await store.add_file(actor, a.summary.session_id, doc)
            with pytest.raises(AppError) as raised:
                await store.submit(actor,
                    b.summary.session_id, SessionSubmission("bad", "hi", (doc.file_id,))
                )
            assert raised.value.status_code == 404
            assert not (await store.read(actor, b.summary.session_id)).messages
            with pytest.raises(AppError):
                await store.submit(actor, a.summary.session_id, SessionSubmission("nul", "\x00"))
            run = await store.submit(actor,
                a.summary.session_id, SessionSubmission("good", "hi", (doc.file_id,))
            )
            original = store._run
            count = 0

            async def broken(*args):
                nonlocal count
                count += 1
                if count == 2:
                    raise RuntimeError("rollback after writes")
                return await original(*args)

            monkeypatch.setattr(store, "_run", broken)
            with pytest.raises(RuntimeError):
                await store.finish(actor,
                    a.summary.session_id, run.run.run_id, RunCompletion("succeeded", "未提交")
                )
            monkeypatch.setattr(store, "_run", original)
            assert len((await store.read(actor, a.summary.session_id)).messages) == 1
            assert (
                await store.read_run(actor, a.summary.session_id, run.run.run_id)
            ).status == "queued"
        finally:
            await store.database.aclose()

    asyncio.run(scenario())
