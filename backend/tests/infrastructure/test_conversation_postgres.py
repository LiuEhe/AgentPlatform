"""PostgreSQL 历史的真实事务与结构回归。"""

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest

SCHEMA = Path(__file__).parents[2] / "database/schema_v2.sql"


def test_schema_is_explicit_transaction_without_destructive_statements():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert sql.strip().startswith("BEGIN;")
    assert sql.strip().endswith("COMMIT;")
    assert "DROP " not in sql.upper()
    assert "IF NOT EXISTS" not in sql.upper()


def test_schema_version_and_reinitialization(postgres_target):
    import asyncpg

    async def scenario():
        dsn, schema = postgres_target
        conn = await asyncpg.connect(dsn, server_settings={"search_path": schema})
        try:
            assert await conn.fetchval("SELECT version FROM chat_schema_version") == 2
            with pytest.raises(asyncpg.DuplicateTableError):
                await conn.execute(SCHEMA.read_text(encoding="utf-8"))
            await conn.execute("ROLLBACK")
            assert await conn.fetchval("SELECT version FROM chat_schema_version") == 2
        finally:
            await conn.close()

    asyncio.run(scenario())


def test_concurrent_duplicate_submission_is_persistent(postgres_target):
    from app.core.config import Settings
    from app.infrastructure.conversation.postgres_store import PostgresConversationStore
    from app.schemas.conversation_session import RunCompletion, SessionSubmission

    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Settings(_env_file=None, database_url=dsn), _schema=schema
        )
        await store.initialize()
        try:
            page = await store.create("conversation_assistant")
            request = SessionSubmission("m1", "你好 😀\nSELECT * FROM users;")
            first, second = await asyncio.gather(
                store.submit(page.summary.session_id, request),
                store.submit(page.summary.session_id, request),
            )
            assert first.run.run_id == second.run.run_id
            assert sum(r.created for r in (first, second)) == 1
            await store.finish(
                page.summary.session_id, first.run.run_id, RunCompletion("succeeded", "收到")
            )
            await store.finish(
                page.summary.session_id, first.run.run_id, RunCompletion("cancelled", "已停止")
            )
            restored = await store.read(page.summary.session_id)
            assert [m.content for m in restored.messages] == [request.content, "收到"]
        finally:
            await store.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("committed", [False, True])
def test_file_confirmation_waits_for_original_transaction(postgres_target, committed):
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.infrastructure.conversation.postgres_store import PostgresConversationStore

    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Settings(_env_file=None, database_url=dsn), _schema=schema
        )
        await store.initialize()
        lookup = None
        try:
            page = await store.create()
            session_id, file_id = UUID(page.summary.session_id), uuid4()
            async with store._pool.acquire() as writer:
                # 预热另一条连接，等待时间只衡量事务锁，不包含建连耗时。
                async with store._pool.acquire():
                    pass
                transaction = writer.transaction()
                await transaction.start()
                try:
                    await writer.execute(
                        "SELECT session_id FROM chat_sessions WHERE session_id=$1 FOR UPDATE",
                        session_id,
                    )
                    await writer.execute(
                        "INSERT INTO files(file_id,session_id,original_name,source_path,"
                        "content_path,size_bytes,content_chars) VALUES($1,$2,'x.docx',"
                        "'source.docx','content.md',1,1)",
                        file_id, session_id,
                    )
                    lookup = asyncio.create_task(store.get_file(str(session_id), str(file_id)))
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(lookup), 0.1)
                finally:
                    if committed:
                        await transaction.commit()
                    else:
                        await transaction.rollback()
                if committed:
                    assert (await lookup).file_id == str(file_id)
                else:
                    with pytest.raises(AppError) as raised:
                        await lookup
                    assert raised.value.code == "MATERIAL_NOT_FOUND"
        finally:
            if lookup:
                await asyncio.gather(lookup, return_exceptions=True)
            await store.aclose()

    asyncio.run(scenario())


def test_message_capacity_reserves_terminal_failure_text(postgres_target):
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.infrastructure.conversation.postgres_store import PostgresConversationStore
    from app.schemas.conversation_session import RunCompletion, SessionSubmission

    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Settings(_env_file=None, database_url=dsn), _schema=schema
        )
        await store.initialize()
        try:
            session_id = (await store.create()).summary.session_id
            with pytest.raises(AppError) as raised:
                await store.submit(session_id, SessionSubmission("full", "字" * 1000000))
            assert raised.value.code == "CONVERSATION_CAPACITY"
            assert not (await store.read(session_id)).messages
            run = await store.submit(
                session_id, SessionSubmission("reserved", "字" * 999990)
            )
            result = await store.finish(
                session_id, run.run.run_id, RunCompletion("succeeded", "超" * 20)
            )
            assert result.error_code == "CONVERSATION_CAPACITY"
            page = await store.read(session_id)
            assert sum(len(message.content) for message in page.messages) == 1000000
        finally:
            await store.aclose()

    asyncio.run(scenario())
