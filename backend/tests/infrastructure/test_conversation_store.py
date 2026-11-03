"""持久历史不再使用旧内存 TTL。"""
import asyncio
from uuid import UUID

from app.core.config import Settings
from app.infrastructure.conversation.postgres_store import PostgresConversationStore
from app.infrastructure.database import Database


def test_history_created_thirty_days_ago_remains_readable(actor, postgres_target):
    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Database(Settings(_env_file=None, database_url=dsn), schema=schema)
        )
        await store.database.initialize()
        try:
            page = await store.create(actor)
            id = page.summary.session_id
            async with store.transaction(write=True) as conn:
                await conn.execute(
                    "UPDATE chat_sessions SET created_at=now()-interval '30 days', "
                    "updated_at=now()-interval '30 days' WHERE session_id=$1",
                    UUID(id),
                )
            await store.database.aclose()
            await store.database.initialize()
            assert (await store.read(actor, id)).summary.session_id == id
            assert id in [
                item.session_id
                for item in (await store.list(actor, "conversation_assistant")).items
            ]
        finally:
            await store.database.aclose()

    asyncio.run(scenario())
