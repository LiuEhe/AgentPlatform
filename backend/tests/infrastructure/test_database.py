import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import Settings


def test_base_database_is_the_shared_query_and_transaction_surface():
    from app.infrastructure.conversation.postgres_store import PostgresConversationStore
    from app.infrastructure.database import BaseDatabase, Database

    assert issubclass(PostgresConversationStore, BaseDatabase)
    assert all(callable(getattr(BaseDatabase, name)) for name in (
        "fetch", "fetchrow", "fetchval", "execute", "transaction", "maintenance",
    ))
    assert not hasattr(Database, "connection")


def test_bound_queries_use_one_connection_and_do_not_own_pool():
    from app.infrastructure.database import BaseDatabase

    class Connection:
        async def fetchval(self, sql, *args):
            return args[0]

    connection = Connection()
    db = BaseDatabase(SimpleNamespace(check=lambda: None), _connection=connection)
    assert asyncio.run(db.fetchval("SELECT $1", 17)) == 17
    assert db.database is not connection


def test_invalid_schema_rejected_before_connection():
    from app.infrastructure.database import Database

    with pytest.raises(ValueError):
        Database(Settings(_env_file=None), schema="public; DROP SCHEMA public")
