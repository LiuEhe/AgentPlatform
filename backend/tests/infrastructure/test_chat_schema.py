"""新结构初始化与数据库约束在真实 PostgreSQL 上执行。"""

import asyncio
from uuid import uuid4

import asyncpg
import pytest


def test_catalog_and_files_have_metadata_only(postgres_target):
    async def scenario():
        dsn, schema = postgres_target
        conn = await asyncpg.connect(dsn, server_settings={"search_path": schema})
        try:
            assert await conn.fetchval("SELECT version FROM chat_schema_version") == 2
            assert set(await conn.fetch("SELECT agent_id FROM agents")) == {
                ("conversation_assistant",), ("institution_review",)
            }
            columns = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=$1 AND table_name='files'", schema
            )
            assert {r[0] for r in columns} == {
                "file_id", "session_id", "original_name", "source_path", "content_path",
                "size_bytes", "content_chars", "created_at",
            }
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO chat_sessions(session_id,agent_id,title) VALUES($1,'unknown','x')",
                    uuid4(),
                )
            first, second, run, message, file = [uuid4() for _ in range(5)]
            for session in (first, second):
                await conn.execute(
                    "INSERT INTO chat_sessions(session_id,agent_id,title) "
                    "VALUES($1,'conversation_assistant','x')", session,
                )
            await conn.execute(
                "INSERT INTO runs(run_id,session_id,client_message_id,status) "
                "VALUES($1,$2,'client','queued')", run, first,
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO runs(run_id,session_id,client_message_id,status) "
                    "VALUES($1,$2,'client','queued')", uuid4(), first,
                )
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO messages(message_id,session_id,run_id,sequence,role,content) "
                    "VALUES($1,$2,$3,1,'user','x')", message, second, run,
                )
            await conn.execute(
                "INSERT INTO messages(message_id,session_id,run_id,sequence,role,content) "
                "VALUES($1,$2,$3,1,'user','x')", message, first, run,
            )
            await conn.execute(
                "INSERT INTO files(file_id,session_id,original_name,source_path,content_path,"
                "size_bytes,content_chars) "
                "VALUES($1,$2,'x.docx','a/source.docx','a/content.md',1,1)",
                file,
                second,
            )
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO message_files VALUES($1,$2,$3,0)", first, message, file
                )
        finally:
            await conn.close()

    asyncio.run(scenario())
