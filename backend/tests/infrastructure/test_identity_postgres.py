import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.database import Database


def test_registration_and_revocable_session_are_real_transactions(postgres_target, tmp_path):
    from app.infrastructure.identity.postgres_store import IdentityStore

    async def scenario():
        dsn, schema = postgres_target
        settings = Settings(_env_file=None, database_url=dsn, documents_dir=tmp_path)
        database = Database(settings, schema=schema)
        await database.initialize()
        store = IdentityStore(database)
        try:
            user = await store.register_user("alice", "Alice", "encoded")
            assert user.role == "user" and user.status == "active"
            assert not user.must_change_password
            with pytest.raises(AppError) as error:
                await store.register_user("alice", "Other", "encoded")
            assert error.value.code == "USERNAME_EXISTS"
            token_hash = hashlib.sha256(b"random test cookie").digest()
            context = await store.issue_session(
                user.user_id, "encoded", None, token_hash, "csrf-token",
                datetime.now(UTC) + timedelta(hours=12),
            )
            assert (await store.read_context(token_hash)).auth_session_id == context.auth_session_id
            await store.revoke_session(context)
            with pytest.raises(AppError) as expired:
                await store.read_context(token_hash)
            assert expired.value.code == "AUTH_REQUIRED"
            with pytest.raises(AppError) as forged:
                await store.issue_session(user.user_id, "old-hash", None,
                                          hashlib.sha256(uuid4().bytes).digest(), "csrf",
                                          datetime.now(UTC) + timedelta(hours=12))
            assert forged.value.code == "INVALID_CREDENTIALS"
        finally:
            await database.aclose()

    asyncio.run(scenario())
