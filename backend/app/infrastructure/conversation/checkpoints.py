"""会话共享的官方 PostgreSQL 检查点资源，不实现检查点协议或业务 SQL。"""

import asyncio
import re
import sys

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import Error as PsycopgError
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import Settings
from app.core.errors import AppError


def event_loop_factory() -> asyncio.AbstractEventLoop:
    """Psycopg 官方异步驱动在 Windows 上要求 Selector loop。"""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


class CheckpointResources:
    def __init__(self, settings: Settings, *, schema: str = "public"):
        if not re.fullmatch(r"public|history_test_[0-9a-f]{32}", schema):
            raise ValueError("Invalid database schema")
        self.settings, self.schema = settings, schema
        self._pool = None
        self.saver = None

    async def open(self) -> None:
        if self._pool is not None:
            return
        if not self.settings.database_url:
            raise AppError("STORAGE_UNAVAILABLE", "数据库暂时不可用，请稍后重试", 503)
        timeout = self.settings.database_timeout_seconds
        self._pool = AsyncConnectionPool(
            self.settings.database_url.get_secret_value(),
            min_size=self.settings.database_pool_min_size,
            max_size=self.settings.database_pool_max_size,
            open=False,
            timeout=timeout,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "prepare_threshold": 0,
                "connect_timeout": max(1, int(timeout)),
                "options": (
                    f"-c search_path={self.schema} "
                    f"-c statement_timeout={int(timeout * 1000)} -c lock_timeout=1000"
                ),
            },
        )
        try:
            await self._pool.open(wait=True, timeout=timeout)
            self.saver = AsyncPostgresSaver(self._pool)
        except (PsycopgError, OSError, TimeoutError):
            await self.aclose()
            raise AppError("STORAGE_UNAVAILABLE", "数据库暂时不可用，请稍后重试", 503) from None

    async def setup(self) -> None:
        """仅显式维护入口调用；应用启动不调用。"""
        await self.saver.setup()

    async def assert_ready(self) -> None:
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT to_regclass(%s) IS NOT NULL AS present",
                        (f"{self.schema}.checkpoint_migrations",),
                    )
                    if not (await cursor.fetchone())["present"]:
                        raise AppError("STORAGE_SCHEMA_INVALID", "检查点结构尚未初始化", 503)
                    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                        await cursor.execute(
                            "SELECT to_regclass(%s) IS NOT NULL AS present",
                            (f"{self.schema}.{table}",),
                        )
                        if not (await cursor.fetchone())["present"]:
                            raise AppError("STORAGE_SCHEMA_INVALID", "检查点结构尚未初始化", 503)
        except (PsycopgError, OSError, TimeoutError):
            raise AppError("STORAGE_UNAVAILABLE", "数据库暂时不可用，请稍后重试", 503) from None

    async def delete_thread(self, thread_id: str) -> None:
        try:
            await self.saver.adelete_thread(thread_id)
        except (PsycopgError, OSError, TimeoutError):
            raise AppError("STORAGE_UNAVAILABLE", "记忆清理暂时不可用，请稍后重试", 503) from None

    async def aclose(self) -> None:
        pool, self._pool = self._pool, None
        self.saver = None
        if pool is not None:
            await pool.close()
