"""PostgreSQL 历史的真实事务与结构回归。"""
import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.infrastructure.database import Database

SCHEMA = Path(__file__).parents[2] / "database/schema_v3.sql"


@pytest.mark.parametrize("rollback", [False, True])
def test_delete_session_removes_all_owned_rows(actor, postgres_target, rollback):
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.infrastructure.conversation.postgres_store import PostgresConversationStore
    from app.schemas.conversation_session import RunCompletion, SessionFile, SessionSubmission
    from app.schemas.conversation_turn import ChildAgentResult

    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Database(Settings(_env_file=None, database_url=dsn), schema=schema)
        )
        await store.database.initialize()
        try:
            sid = (await store.create(actor)).summary.session_id
            other = (await store.create(actor)).summary.session_id
            fid = str(uuid4())
            await store.add_file(actor, sid, SessionFile(
                file_id=fid, session_id=sid, original_name="x.docx",
                source_path="s", content_path="c",
                size_bytes=1, content_chars=1,
            ))
            run = await store.submit(actor, sid, SessionSubmission("first", "hi", (fid,)))
            call = ChildAgentResult(
                id=str(uuid4()), agent_id="institution_review", agent_name="review",
                invocation_id="inv", output_type="markdown", output="report",
            )
            await store.finish(actor,
                sid, run.run.run_id, RunCompletion("succeeded", "answer", child_call=call)
            )
            for status in ("failed", "cancelled"):
                item = await store.submit(actor, sid, SessionSubmission(status, status))
                await store.finish(actor, sid, item.run.run_id, RunCompletion(status, status))
            before = await store.inspect_deletion(actor, sid)
            assert len(before.run_ids) == 3 and before.active_run_id is None
            if rollback:
                async with store.transaction(write=True) as conn:
                    await conn.execute("""CREATE FUNCTION reject_delete() RETURNS trigger AS $$
                        BEGIN RAISE EXCEPTION 'reject'; END; $$ LANGUAGE plpgsql;
                        CREATE TRIGGER reject_delete BEFORE DELETE ON chat_sessions
                        FOR EACH ROW EXECUTE FUNCTION reject_delete();""")
                with pytest.raises(AppError):
                    await store.delete_session(actor, sid)
                assert len((await store.read(actor, sid)).messages) == 6
                assert (await store.read(actor, sid)).files[0].file_id == fid
                return
            await store.delete_session(actor, sid)
            await store.delete_session(actor, sid)
            assert await store.inspect_deletion(actor, sid) is None
            async with store.transaction(write=True) as conn:
                for table in ("runs", "messages", "files", "message_files", "agent_calls"):
                    assert await conn.fetchval(f"SELECT count(*) FROM {table}") == 0
                assert await conn.fetchval("SELECT count(*) FROM agents") == 2
                assert await conn.fetchval("SELECT version FROM chat_schema_version") == 3
            assert (await store.read(actor, other)).summary.session_id == other
        finally:
            await store.database.aclose()
    asyncio.run(scenario())


def test_delete_session_rejects_active_run(actor, postgres_target):
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.infrastructure.conversation.postgres_store import PostgresConversationStore
    from app.schemas.conversation_session import SessionSubmission

    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Database(Settings(_env_file=None, database_url=dsn), schema=schema)
        )
        await store.database.initialize()
        try:
            sid = (await store.create(actor)).summary.session_id
            run = await store.submit(actor, sid, SessionSubmission("one", "hello"))
            for status in ("queued", "running"):
                if status == "running":
                    await store.start(actor, sid, run.run.run_id)
                with pytest.raises(AppError) as raised:
                    await store.delete_session(actor, sid)
                assert raised.value.code == "CONVERSATION_BUSY"
                assert len((await store.read(actor, sid)).messages) == 1
            with pytest.raises(AppError) as invalid:
                await store.inspect_deletion(actor, "invalid")
            assert invalid.value.status_code == 404
        finally:
            await store.database.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize("committed", [False, True])
def test_deletion_confirmation_waits_for_original_transaction(actor, postgres_target, committed):
    from app.core.config import Settings
    from app.infrastructure.conversation.postgres_store import PostgresConversationStore

    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Database(Settings(_env_file=None, database_url=dsn), schema=schema)
        )
        await store.database.initialize()
        try:
            sid = (await store.create(actor)).summary.session_id
            transaction = store.transaction(write=True)
            writer = await transaction.__aenter__()
            await writer.execute("DELETE FROM chat_sessions WHERE session_id=$1", UUID(sid))
            lookup = asyncio.create_task(store.inspect_deletion(actor, sid))
            try:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(lookup), .1)
            finally:
                failure = None if committed else RuntimeError("controlled rollback")
                await transaction.__aexit__(type(failure) if failure else None, failure, None)
            result = await lookup
            assert (result is None) is committed
        finally:
            await store.database.aclose()
    asyncio.run(scenario())


def test_schema_is_explicit_transaction_without_destructive_statements():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE TABLE users" in sql
    assert "BEGIN;" not in sql  # The maintenance command owns the transaction.
    assert "DROP " not in sql.upper()
    assert "IF NOT EXISTS" not in sql.upper()


def test_schema_version_and_reinitialization(postgres_target):
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.infrastructure.database import BaseDatabase
    async def scenario():
        dsn, schema = postgres_target
        async with BaseDatabase.maintenance(
            Settings(_env_file=None, database_url=dsn), schema=schema
        ) as conn:
            assert await conn.fetchval("SELECT version FROM chat_schema_version") == 3
            with pytest.raises(AppError):
                async with conn.transaction(write=True) as tx:
                    await tx.execute(SCHEMA.read_text(encoding="utf-8"))
            assert await conn.fetchval("SELECT version FROM chat_schema_version") == 3
    asyncio.run(scenario())


def test_concurrent_duplicate_submission_is_persistent(actor, postgres_target):
    from app.core.config import Settings
    from app.infrastructure.conversation.postgres_store import PostgresConversationStore
    from app.schemas.conversation_session import RunCompletion, SessionSubmission

    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Database(Settings(_env_file=None, database_url=dsn), schema=schema)
        )
        await store.database.initialize()
        try:
            page = await store.create(actor, "conversation_assistant")
            request = SessionSubmission("m1", "你好 😀\nSELECT * FROM users;")
            first, second = await asyncio.gather(
                store.submit(actor, page.summary.session_id, request),
                store.submit(actor, page.summary.session_id, request),
            )
            assert first.run.run_id == second.run.run_id
            assert sum(r.created for r in (first, second)) == 1
            await store.finish(actor,
                page.summary.session_id, first.run.run_id, RunCompletion("succeeded", "收到")
            )
            await store.finish(actor,
                page.summary.session_id, first.run.run_id, RunCompletion("cancelled", "已停止")
            )
            restored = await store.read(actor, page.summary.session_id)
            assert [m.content for m in restored.messages] == [request.content, "收到"]
        finally:
            await store.database.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("committed", [False, True])
def test_file_confirmation_waits_for_original_transaction(actor, postgres_target, committed):
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.infrastructure.conversation.postgres_store import PostgresConversationStore

    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Database(Settings(_env_file=None, database_url=dsn), schema=schema)
        )
        await store.database.initialize()
        lookup = None
        try:
            page = await store.create(actor)
            session_id, file_id = UUID(page.summary.session_id), uuid4()
            transaction = store.transaction(write=True)
            writer = await transaction.__aenter__()
            try:
                await writer.execute(
                    "SELECT session_id FROM chat_sessions WHERE session_id=$1 FOR UPDATE",
                    session_id,
                )
                await writer.execute(
                    "INSERT INTO files(file_id,session_id,original_name,source_path,"
                    "content_path,size_bytes,content_chars) VALUES($1,$2,'x.docx','source.docx',"
                    "'content.md',1,1)",
                    file_id,
                    session_id,
                )
                lookup = asyncio.create_task(store.get_file(actor, str(session_id), str(file_id)))
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(lookup), .1)
            finally:
                failure = None if committed else RuntimeError("controlled rollback")
                await transaction.__aexit__(type(failure) if failure else None, failure, None)
            if committed:
                assert (await lookup).file_id == str(file_id)
            else:
                with pytest.raises(AppError) as raised:
                    await lookup
                assert raised.value.code == "MATERIAL_NOT_FOUND"
        finally:
            if lookup:
                await asyncio.gather(lookup, return_exceptions=True)
            await store.database.aclose()

    asyncio.run(scenario())


def test_message_capacity_reserves_terminal_failure_text(actor, postgres_target):
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.infrastructure.conversation.postgres_store import PostgresConversationStore
    from app.schemas.conversation_session import RunCompletion, SessionSubmission

    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Database(Settings(_env_file=None, database_url=dsn), schema=schema)
        )
        await store.database.initialize()
        try:
            session_id = (await store.create(actor)).summary.session_id
            with pytest.raises(AppError) as raised:
                await store.submit(actor, session_id, SessionSubmission("full", "字" * 1000000))
            assert raised.value.code == "CONVERSATION_CAPACITY"
            assert not (await store.read(actor, session_id)).messages
            run = await store.submit(actor,
                session_id, SessionSubmission("reserved", "字" * 999990)
            )
            result = await store.finish(actor,
                session_id, run.run.run_id, RunCompletion("succeeded", "超" * 20)
            )
            assert result.error_code == "CONVERSATION_CAPACITY"
            page = await store.read(actor, session_id)
            assert sum(len(message.content) for message in page.messages) == 1000000
        finally:
            await store.database.aclose()

    asyncio.run(scenario())
