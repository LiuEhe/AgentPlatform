"""账号与可撤销登录仓储；所有SQL经统一基类执行。"""

import base64
import json
from datetime import datetime
from uuid import UUID, uuid4

from app.core.errors import AppError
from app.infrastructure.database import BaseDatabase, DatabaseConstraintError
from app.schemas.identity import (
    PROFILE_FIELDS,
    AuthContext,
    AvatarChange,
    UserIdentity,
    UserPage,
    UserProfile,
    UserRecord,
)


def auth_required():
    return AppError("AUTH_REQUIRED", "登录已失效，请重新登录", 401)


def _identity(row):
    values = {key: row[key] for key in UserIdentity.model_fields if key != "has_avatar"}
    return UserIdentity(**values, has_avatar=row["avatar_path"] is not None)


def _profile(row):
    return UserProfile(**_identity(row).model_dump(), **{
        key: row[key] for key in ("email", "gender", "birthday", "phone_number", "address", "bio")
    })


def _context(row):
    return AuthContext(_identity(row), row["auth_session_id"], row["csrf_token"], row["expires_at"])


LIVE = (
    "SELECT u.*,s.auth_session_id,s.csrf_token,s.expires_at FROM auth_sessions s "
    "JOIN users u ON u.user_id=s.user_id WHERE s.revoked_at IS NULL "
    "AND s.expires_at>now() AND u.status='active' "
)


class IdentityStore(BaseDatabase):
    async def assert_bootstrap_admin(self):
        if not await self.fetchval(
            "SELECT EXISTS(SELECT 1 FROM users WHERE username='admin' "
            "AND role='admin' AND status='active')",
        ):
            raise AppError("STORAGE_SCHEMA_INVALID", "请先显式初始化管理员账号", 503)

    async def find_user(self, username):
        row = await self.fetchrow("SELECT * FROM users WHERE username=$1", username)
        return UserRecord(_identity(row), row["password_hash"]) if row else None

    async def read_context(self, token_hash):
        row = await self.fetchrow(LIVE + "AND s.token_hash=$1", token_hash)
        if row is None:
            raise auth_required()
        return _context(row)

    async def assert_live(self, actor):
        row = await self.fetchrow(
            LIVE + "AND s.auth_session_id=$1 AND s.user_id=$2",
            actor.auth_session_id, actor.user.user_id,
        )
        if row is None:
            raise auth_required()
        return _context(row)

    async def lock_actor(self, tx, actor, *, allow_password_change=False):
        # 先锁用户，再以新read-committed语句验证登录，确保等待停用/改密后读取新状态。
        row = await tx.fetchrow("SELECT * FROM users WHERE user_id=$1 FOR UPDATE",
                                actor.user.user_id)
        if row is None or row["status"] != "active":
            raise auth_required()
        valid = await tx.fetchval(
            "SELECT EXISTS(SELECT 1 FROM auth_sessions WHERE auth_session_id=$1 "
            "AND user_id=$2 AND revoked_at IS NULL AND expires_at>now())",
            actor.auth_session_id, actor.user.user_id,
        )
        if not valid:
            raise auth_required()
        if row["must_change_password"] and not allow_password_change:
            raise AppError("PASSWORD_CHANGE_REQUIRED", "请先修改临时密码", 403)
        return _identity(row)

    async def _admin(self, tx, actor):
        user = await self.lock_actor(tx, actor)
        if user.role != "admin":
            raise AppError("FORBIDDEN", "没有管理用户的权限", 403)
        return user

    @staticmethod
    def _constraint(exc):
        if exc.sqlstate == "23505" and exc.constraint_name == "users_username_key":
            raise AppError("USERNAME_EXISTS", "用户名已被使用或保留", 409) from None
        raise AppError("STORAGE_UNAVAILABLE", "账号保存失败，请稍后重试", 503) from None

    async def _insert(self, tx, username, display_name, password_hash, *, temporary):
        if username == "admin":
            raise AppError("USERNAME_EXISTS", "用户名已被使用或保留", 409)
        row = await tx.fetchrow(
            "INSERT INTO users(user_id,username,display_name,password_hash,role,status,"
            "must_change_password) VALUES($1,$2,$3,$4,'user','active',$5) RETURNING *",
            uuid4(), username, display_name, password_hash, temporary,
        )
        return _identity(row)

    async def register_user(self, username, display_name, password_hash):
        try:
            async with self.transaction(write=True) as tx:
                return await self._insert(
                    tx, username, display_name, password_hash, temporary=False
                )
        except DatabaseConstraintError as exc:
            self._constraint(exc)

    async def create_user(self, actor, username, display_name, password_hash):
        try:
            async with self.transaction(write=True) as tx:
                await self._admin(tx, actor)
                return await self._insert(tx, username, display_name, password_hash, temporary=True)
        except DatabaseConstraintError as exc:
            self._constraint(exc)

    async def issue_session(self, user_id, expected_hash, old_session_id, token_hash,
                            csrf_token, expires_at, *, replacement_hash=None):
        async with self.transaction(write=True) as tx:
            row = await tx.fetchrow("SELECT * FROM users WHERE user_id=$1 FOR UPDATE", user_id)
            if row is None or row["status"] != "active" or row["password_hash"] != expected_hash:
                raise AppError("INVALID_CREDENTIALS", "用户名或密码错误", 401)
            if old_session_id is not None:
                await tx.execute(
                    "UPDATE auth_sessions SET revoked_at=now() WHERE auth_session_id=$1 "
                    "AND revoked_at IS NULL", old_session_id,
                )
            if replacement_hash is not None:
                await tx.execute("UPDATE users SET password_hash=$1 WHERE user_id=$2",
                                 replacement_hash, user_id)
            session_id = uuid4()
            await tx.execute(
                "INSERT INTO auth_sessions(auth_session_id,user_id,token_hash,csrf_token,"
                "expires_at) "
                "VALUES($1,$2,$3,$4,$5)",
                session_id,
                user_id,
                token_hash,
                csrf_token,
                expires_at,
            )
            await tx.execute(
                "DELETE FROM auth_sessions WHERE auth_session_id IN "
                "(SELECT auth_session_id FROM auth_sessions WHERE expires_at<=now() LIMIT 100)",
            )
            return AuthContext(_identity(row), session_id, csrf_token, expires_at)

    async def revoke_session(self, actor):
        async with self.transaction(write=True) as tx:
            await self.lock_actor(tx, actor, allow_password_change=True)
            await tx.execute("UPDATE auth_sessions SET revoked_at=now() "
                             "WHERE auth_session_id=$1", actor.auth_session_id)

    async def change_password(self, actor, expected_hash, new_hash):
        async with self.transaction(write=True) as tx:
            await self.lock_actor(tx, actor, allow_password_change=True)
            row = await tx.fetchrow("SELECT password_hash FROM users WHERE user_id=$1",
                                    actor.user.user_id)
            if row["password_hash"] != expected_hash:
                raise AppError("PASSWORD_INVALID", "当前密码已改变，请重新登录", 422)
            await tx.execute(
                "UPDATE users SET password_hash=$1,must_change_password=false,updated_at=now() "
                "WHERE user_id=$2", new_hash, actor.user.user_id,
            )
            await tx.execute("UPDATE auth_sessions SET revoked_at=now() "
                             "WHERE user_id=$1 AND revoked_at IS NULL", actor.user.user_id)

    async def _profile_row(self, tx, actor, target_user_id=None):
        if target_user_id is None:
            await self.lock_actor(tx, actor)
            target_user_id = actor.user.user_id
        else:
            await self._admin(tx, actor)
        row = await tx.fetchrow("SELECT * FROM users WHERE user_id=$1", target_user_id)
        if row is None:
            raise AppError("USER_NOT_FOUND", "用户不存在", 404)
        return row

    async def read_profile(self, actor, *, target_user_id=None):
        async with self.transaction(write=True) as tx:
            return _profile(await self._profile_row(tx, actor, target_user_id))

    async def read_avatar_path(self, actor, *, target_user_id=None):
        async with self.transaction(write=True) as tx:
            return (await self._profile_row(tx, actor, target_user_id))["avatar_path"]

    async def update_profile(self, actor, changes):
        if not changes.keys() <= PROFILE_FIELDS:
            raise AppError("VALIDATION_ERROR", "资料字段无效", 422)
        async with self.transaction(write=True) as tx:
            await self.lock_actor(tx, actor)
            if not changes:
                return _profile(await tx.fetchrow("SELECT * FROM users WHERE user_id=$1",
                                                  actor.user.user_id))
            names = sorted(changes)
            assignments = ",".join(f"{name}=${index}" for index, name in enumerate(names, 1))
            row = await tx.fetchrow(
                f"UPDATE users SET {assignments},updated_at=now() "
                f"WHERE user_id=${len(names) + 1} RETURNING *",
                *(changes[name] for name in names), actor.user.user_id,
            )
            return _profile(row)

    async def replace_avatar(self, actor, new_path, *, state):
        async with self.transaction(write=True) as tx:
            await self.lock_actor(tx, actor)
            row = await tx.fetchrow("SELECT * FROM users WHERE user_id=$1", actor.user.user_id)
            previous = row["avatar_path"]
            if previous != new_path:
                row = await tx.fetchrow(
                    "UPDATE users SET avatar_path=$1,updated_at=now() "
                    "WHERE user_id=$2 RETURNING *", new_path, actor.user.user_id,
                )
            result = AvatarChange(_profile(row), previous)
            state.commit_started = True
        return result

    async def _target(self, tx, actor, target_user_id):
        await self._admin(tx, actor)
        row = await tx.fetchrow("SELECT * FROM users WHERE user_id=$1 FOR UPDATE", target_user_id)
        if row is None:
            raise AppError("USER_NOT_FOUND", "用户不存在", 404)
        if row["username"] == "admin":
            raise AppError("BUILTIN_ADMIN_PROTECTED", "内置管理员不能通过此入口修改", 409)
        return row

    async def set_status(self, actor, target_user_id, status):
        async with self.transaction(write=True) as tx:
            await self._target(tx, actor, target_user_id)
            row = await tx.fetchrow(
                "UPDATE users SET status=$1,updated_at=now() WHERE user_id=$2 RETURNING *",
                status, target_user_id,
            )
            if status == "disabled":
                await tx.execute("UPDATE auth_sessions SET revoked_at=now() "
                                 "WHERE user_id=$1 AND revoked_at IS NULL", target_user_id)
            return _identity(row)

    async def reset_password(self, actor, target_user_id, password_hash):
        async with self.transaction(write=True) as tx:
            await self._target(tx, actor, target_user_id)
            await tx.execute(
                "UPDATE users SET password_hash=$1,must_change_password=true,updated_at=now() "
                "WHERE user_id=$2", password_hash, target_user_id,
            )
            await tx.execute("UPDATE auth_sessions SET revoked_at=now() "
                             "WHERE user_id=$1 AND revoked_at IS NULL", target_user_id)

    async def list_users(self, actor, *, limit=20, cursor=None):
        stamp, last_id = None, None
        if cursor:
            try:
                if len(cursor) > 512:
                    raise ValueError
                item = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                if set(item) != {"created_at", "user_id"}:
                    raise ValueError
                stamp, last_id = datetime.fromisoformat(item["created_at"]), UUID(item["user_id"])
                if stamp.tzinfo is None:
                    raise ValueError
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise AppError("VALIDATION_ERROR", "用户分页游标无效", 422) from None
        async with self.transaction(write=True) as tx:
            await self._admin(tx, actor)
            rows = await tx.fetch(
                "SELECT * FROM users WHERE ($1::timestamptz IS NULL "
                "OR (created_at,user_id)<($1,$2::uuid)) "
                "ORDER BY created_at DESC,user_id DESC LIMIT $3", stamp, last_id, limit + 1,
            )
        items = [_identity(row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit:
            last = items[-1]
            next_cursor = base64.urlsafe_b64encode(json.dumps({
                "created_at": last.created_at.isoformat(), "user_id": str(last.user_id),
            }).encode()).decode()
        return UserPage(items, next_cursor)
