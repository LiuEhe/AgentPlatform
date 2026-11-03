"""显式离线账号初始化与管理员密码恢复；不在应用启动中执行。"""

import argparse
import asyncio
from getpass import getpass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.database import BaseDatabase
from app.infrastructure.identity.passwords import PasswordHasher

SQL_ROOT = Path(__file__).resolve().parents[1] / "database"


def _scope(settings, schema):
    if schema != "public" and (
        not settings.database_url
        or urlsplit(settings.database_url.get_secret_value()).path != "/agent_platform_test"
    ):
        raise ValueError("Non-public maintenance is restricted to the explicit test database")


async def _password(password):
    hasher = PasswordHasher()
    try:
        return await hasher.hash(password)
    finally:
        await hasher.aclose()


async def initialize_v3(settings, password, *, schema="public"):
    _scope(settings, schema)
    encoded, user_id = await _password(password), uuid4()
    async with BaseDatabase.maintenance(settings, schema=schema) as db:
        if await db.fetchval("SELECT to_regclass('chat_schema_version')") is not None:
            raise ValueError(
                "Database already initialized; use password reset"
            )
        async with db.transaction(write=True) as tx:
            await tx.execute((SQL_ROOT / "schema_v3.sql").read_text(encoding="utf-8"))
            await tx.execute(
                "INSERT INTO users(user_id,username,display_name,password_hash,role,status,"
                "must_change_password) VALUES($1,'admin','管理员',$2,'admin','active',false)",
                user_id, encoded,
            )
    return user_id


async def reset_admin_password(settings, password, *, schema="public"):
    _scope(settings, schema)
    encoded = await _password(password)
    async with BaseDatabase.maintenance(settings, schema=schema) as db:
        async with db.transaction(write=True) as tx:
            row = await tx.fetchrow("SELECT user_id FROM users WHERE username='admin' FOR UPDATE")
            if not row:
                raise ValueError("Administrator not initialized")
            await tx.execute(
                "UPDATE users SET password_hash=$1,must_change_password=false,updated_at=now() "
                "WHERE user_id=$2", encoded, row["user_id"],
            )
            await tx.execute("UPDATE auth_sessions SET revoked_at=now() "
                             "WHERE user_id=$1 AND revoked_at IS NULL", row["user_id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("initialize", "reset-admin"))
    args = parser.parse_args()
    settings = Settings()
    password = getpass("管理员新密码：")
    if password != getpass("确认新密码："):
        raise SystemExit("两次密码不一致")
    operation = (
        initialize_v3(settings, password)
        if args.operation == "initialize"
        else reset_admin_password(settings, password)
    )
    try:
        asyncio.run(operation)
    except (AppError, ValueError, OSError, KeyError) as exc:
        raise SystemExit(
            f"维护失败（{type(exc).__name__}），请检查目标数据库与初始化状态"
        ) from None
    print("维护操作完成；未重做任何模型任务。")


if __name__ == "__main__":
    main()
