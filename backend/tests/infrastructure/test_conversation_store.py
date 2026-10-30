"""持久历史不再使用旧内存 TTL。"""

import asyncio
from uuid import UUID

from app.core.config import Settings
from app.infrastructure.conversation.postgres_store import PostgresConversationStore


def test_history_created_thirty_days_ago_remains_readable(postgres_target):
    async def scenario():
        dsn, schema = postgres_target
        store = PostgresConversationStore(
            Settings(_env_file=None, database_url=dsn), _schema=schema
        )
        await store.initialize()
        try:
            page = await store.create()
            id = page.summary.session_id
            async with store._connection(write=True) as conn:
                await conn.execute(
                    "UPDATE chat_sessions SET created_at=now()-interval '30 days', "
                    "updated_at=now()-interval '30 days' WHERE session_id=$1",
                    UUID(id),
                )
            await store.aclose()
            await store.initialize()
            assert (await store.read(id)).summary.session_id == id
            assert id in [
                item.session_id for item in (await store.list("conversation_assistant")).items
            ]
        finally:
            await store.aclose()

    asyncio.run(scenario())
