"""统一数据库执行基类及共享资源；原始驱动连接不离开本模块。"""

import asyncio
import re
from contextlib import asynccontextmanager

import asyncpg

from app.core.errors import AppError

OWNER_LOCK = (1095782471, 1)


class DatabaseConstraintError(Exception):
    def __init__(self, sqlstate, constraint_name):
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name
        super().__init__("Database constraint rejected")


def _unavailable():
    return AppError("STORAGE_UNAVAILABLE", "数据库暂时不可用，请稍后重试", 503)


class Database:
    def __init__(self, settings, *, schema="public", on_unavailable=None):
        if not re.fullmatch(r"public|history_test_[0-9a-f]{32}", schema):
            raise ValueError("Invalid database schema")
        self.settings, self.schema = settings, schema
        self._pool = self._owner = None
        self._available = False
        self.on_unavailable = on_unavailable

    def _options(self):
        return dict(
            timeout=self.settings.database_timeout_seconds,
            command_timeout=self.settings.database_timeout_seconds,
            server_settings={"search_path": self.schema, "statement_timeout": "5000",
                             "lock_timeout": "1000"},
        )

    async def _open_owner(self):
        if not self.settings.database_url:
            raise _unavailable()
        self._owner = await asyncpg.connect(
            self.settings.database_url.get_secret_value(), **self._options(),
        )
        if not await self._owner.fetchval("SELECT pg_try_advisory_lock($1,$2)", *OWNER_LOCK):
            raise AppError("STORAGE_IN_USE", "已有进程使用数据库，请使用单工作进程", 503)
        self._owner.add_termination_listener(self._lost_owner)
        self._available = True

    async def initialize(self):
        try:
            await self._open_owner()
            self._pool = await asyncpg.create_pool(
                self.settings.database_url.get_secret_value(),
                min_size=self.settings.database_pool_min_size,
                max_size=self.settings.database_pool_max_size, **self._options(),
            )
        except BaseException as exc:
            await self.aclose()
            if isinstance(exc, (AppError, asyncio.CancelledError)):
                raise
            raise _unavailable() from None

    def _lost_owner(self, _connection):
        self._available = False
        if self.on_unavailable:
            self.on_unavailable()

    def check(self):
        if not self._available or not self._owner or self._owner.is_closed():
            raise _unavailable()

    async def aclose(self):
        self._available = False
        if self._pool:
            try:
                await asyncio.wait_for(self._pool.close(), 10)
            except TimeoutError:
                self._pool.terminate()
            self._pool = None
        if self._owner:
            self._owner.remove_termination_listener(self._lost_owner)
            await self._owner.close(timeout=5)
            self._owner = None


class BaseDatabase:
    def __init__(self, database, *, _connection=None):
        self.database = database
        self._bound = _connection

    @asynccontextmanager
    async def transaction(self, *, write=False):
        self.database.check()
        try:
            if self._bound is not None:
                async with self._bound.transaction(
                    isolation="read_committed" if write else "repeatable_read", readonly=not write,
                ):
                    yield BaseDatabase(self.database, _connection=self._bound)
                    self.database.check()
            else:
                async with self.database._pool.acquire(
                    timeout=self.database.settings.database_timeout_seconds,
                ) as conn:
                    async with conn.transaction(
                        isolation="read_committed" if write else "repeatable_read",
                        readonly=not write,
                    ):
                        yield BaseDatabase(self.database, _connection=conn)
                        self.database.check()
        except asyncpg.IntegrityConstraintViolationError as exc:
            raise DatabaseConstraintError(exc.sqlstate, exc.constraint_name) from None
        except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError):
            raise _unavailable() from None

    async def _query(self, method, sql, args, *, write=False):
        if self._bound is not None:
            self.database.check()
            try:
                return await getattr(self._bound, method)(sql, *args)
            except asyncpg.IntegrityConstraintViolationError as exc:
                raise DatabaseConstraintError(exc.sqlstate, exc.constraint_name) from None
            except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError):
                raise _unavailable() from None
        async with self.transaction(write=write) as tx:
            return await tx._query(method, sql, args)

    async def fetch(self, sql, *args):
        return await self._query("fetch", sql, args)

    async def fetchrow(self, sql, *args):
        return await self._query("fetchrow", sql, args)

    async def fetchval(self, sql, *args):
        return await self._query("fetchval", sql, args)

    async def execute(self, sql, *args):
        return await self._query("execute", sql, args, write=True)

    @classmethod
    @asynccontextmanager
    async def maintenance(cls, settings, *, schema="public"):
        database = Database(settings, schema=schema)
        try:
            await database._open_owner()
            yield cls(database, _connection=database._owner)
        except asyncpg.IntegrityConstraintViolationError as exc:
            raise DatabaseConstraintError(exc.sqlstate, exc.constraint_name) from None
        except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError):
            raise _unavailable() from None
        finally:
            await database.aclose()
