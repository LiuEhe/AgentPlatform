import asyncio
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.infrastructure.identity.postgres_store import IdentityStore
from app.schemas.identity import AuthContext, AvatarWriteState, UserIdentity


def make_store():
    now = datetime.now(UTC)
    uid, other = uuid4(), uuid4()
    row = dict(user_id=uid, username="alice", display_name="Alice", password_hash="secret",
               role="user", status="active", must_change_password=False, avatar_path=None,
               email="old@example.com", gender=None, birthday=None, phone_number=None,
               address=None, bio="old", created_at=now, updated_at=now)
    rows = {uid: row, other: {**row, "user_id": other, "username": "bob", "status": "disabled"}}
    values = {key: row[key] for key in UserIdentity.model_fields if key != "has_avatar"}
    user = UserIdentity(**values, has_avatar=False)
    actor = AuthContext(user, uuid4(), "csrf", now + timedelta(hours=1))
    calls, commit_errors = [], []

    class Tx:
        async def fetchrow(self, sql, *args):
            calls.append((sql, args))
            result = rows.get(args[-1] if sql.startswith("UPDATE") else args[0])
            if result and sql.startswith("UPDATE"):
                for name, index in re.findall(r"(\w+)=\$(\d+)", sql.split(" WHERE ")[0]):
                    result[name] = args[int(index) - 1]
                result["updated_at"] = now + timedelta(seconds=1)
            return dict(result) if result else None

        async def fetchval(self, sql, *args):
            return True

    @asynccontextmanager
    async def transaction(**kwargs):
        yield Tx()
        if commit_errors:
            raise commit_errors.pop()

    store = object.__new__(IdentityStore)
    store.transaction = transaction
    return SimpleNamespace(store=store, actor=actor, rows=rows, other=other,
                           calls=calls, errors=commit_errors)


def test_profile_patch_keeps_omitted_fields():
    async def scenario():
        f = make_store()
        changed = await f.store.update_profile(f.actor, {"bio": "new"})
        assert changed.bio == "new" and changed.email == "old@example.com"
        update = next(sql for sql, _ in f.calls if sql.startswith("UPDATE"))
        assert "email=" not in update
        assert (await f.store.update_profile(f.actor, {"email": None})).email is None
        f.calls.clear()
        unchanged = await f.store.update_profile(f.actor, {})
        assert unchanged.bio == "new"
        assert not any(sql.startswith("UPDATE") for sql, _ in f.calls)
        with pytest.raises(AppError):
            await f.store.update_profile(f.actor, {"role": "admin"})
        assert "avatar_path" not in changed.model_dump()
        assert "password_hash" not in changed.model_dump()
    asyncio.run(scenario())


def test_profile_read_requires_owner_or_admin():
    async def scenario():
        f = make_store()
        assert (await f.store.read_profile(f.actor)).user_id == f.actor.user.user_id
        with pytest.raises(AppError) as denied:
            await f.store.read_profile(f.actor, target_user_id=f.other)
        assert denied.value.code == "FORBIDDEN"
        f.rows[f.actor.user.user_id]["role"] = "admin"
        assert (await f.store.read_profile(f.actor, target_user_id=f.other)).status == "disabled"
        own = await f.store.read_profile(f.actor, target_user_id=f.actor.user.user_id)
        assert own.role == "admin"
        with pytest.raises(AppError) as missing:
            await f.store.read_profile(f.actor, target_user_id=uuid4())
        assert missing.value.code == "USER_NOT_FOUND"
    asyncio.run(scenario())


def test_avatar_commit_phase_is_recorded():
    async def scenario():
        f = make_store()
        state = AvatarWriteState()
        path = f"{f.actor.user.user_id}/{uuid4()}.png"
        result = await f.store.replace_avatar(f.actor, path, state=state)
        assert state.commit_started and result.previous_path is None
        assert result.profile.has_avatar
        assert await f.store.read_avatar_path(f.actor) == path
        f.errors.append(AppError("STORAGE_UNAVAILABLE", "unknown", 503))
        state = AvatarWriteState()
        with pytest.raises(AppError):
            await f.store.replace_avatar(f.actor, None, state=state)
        assert state.commit_started
        f.rows[f.actor.user.user_id]["status"] = "disabled"
        state = AvatarWriteState()
        with pytest.raises(AppError):
            await f.store.replace_avatar(f.actor, path, state=state)
        assert not state.commit_started
    asyncio.run(scenario())
