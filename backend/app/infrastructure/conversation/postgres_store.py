"""会话历史 PostgreSQL 仓储；不导入 HTTP View 或 Agent 业务。"""

import asyncio
import base64
import json
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID, uuid4

import asyncpg

from app.core.errors import AppError
from app.schemas.conversation_session import (
    ChatSessionListPage,
    ChatSessionPage,
    ChatSessionSummary,
    RunCompletion,
    SessionFile,
    SessionMessage,
    SessionRun,
    SessionSnapshot,
    SessionSubmission,
    SubmissionResult,
)
from app.schemas.conversation_turn import ChildAgentResult, ContinuationState

TERMINAL = {"succeeded", "failed", "cancelled"}
CAPACITY_MESSAGE = "会话输出超过容量限制"


def identifier(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise AppError("CONVERSATION_NOT_FOUND", "记录不存在", 404) from None


def validate_text(*values: str):
    if any("\x00" in value for value in values):
        raise AppError("INVALID_CONVERSATION_INPUT", "内容包含不支持的空字符", 422)


class PostgresConversationStore:
    def __init__(
        self, settings, *, on_unavailable: Callable[[], None] | None = None, _schema="public"
    ):
        if not re.fullmatch(r"public|history_test_[0-9a-f]{32}", _schema):
            raise ValueError("Invalid database schema")
        self.settings = settings
        self._schema = _schema
        self._on_unavailable = on_unavailable
        self._pool = None
        self._owner = None
        self._available = False

    async def initialize(self):
        if not self.settings.database_url:
            raise AppError("STORAGE_UNAVAILABLE", "缺少 DATABASE_URL", 503)
        dsn = self.settings.database_url.get_secret_value()
        options = dict(
            timeout=self.settings.database_timeout_seconds,
            command_timeout=self.settings.database_timeout_seconds,
            server_settings={
                "search_path": self._schema,
                "statement_timeout": "5000",
                "lock_timeout": "1000",
            },
        )
        try:
            self._owner = await asyncpg.connect(dsn, **options)
            if not await self._owner.fetchval("SELECT pg_try_advisory_lock(1095782471, 1)"):
                raise AppError("STORAGE_IN_USE", "已有进程使用会话数据库，请使用单工作进程", 503)
            version = await self._owner.fetchval("SELECT version FROM chat_schema_version")
            if version != 2:
                raise AppError("STORAGE_SCHEMA_INVALID", "会话表结构版本不匹配", 503)
            self._pool = await asyncpg.create_pool(
                dsn,
                min_size=self.settings.database_pool_min_size,
                max_size=self.settings.database_pool_max_size,
                **options,
            )
            self._owner.add_termination_listener(self._lost_owner)
            self._available = True
        except BaseException as exc:
            await self.aclose()
            if isinstance(exc, (AppError, asyncio.CancelledError)):
                raise
            raise AppError("STORAGE_UNAVAILABLE", "数据库连接或会话表结构不可用", 503) from None

    def _lost_owner(self, connection):
        self._available = False
        if self._on_unavailable:
            self._on_unavailable()

    def _check(self):
        if not self._available or not self._owner or self._owner.is_closed():
            raise AppError("STORAGE_UNAVAILABLE", "历史保存服务不可用，请重启服务", 503)

    @asynccontextmanager
    async def _connection(self, *, write=False):
        self._check()
        try:
            async with self._pool.acquire(timeout=self.settings.database_timeout_seconds) as conn:
                async with conn.transaction(
                    isolation="read_committed" if write else "repeatable_read", readonly=not write
                ):
                    yield conn
                    if write:
                        self._check()
        except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError):
            raise AppError("STORAGE_UNAVAILABLE", "会话数据库暂时不可用", 503) from None

    @staticmethod
    def _summary(row):
        return ChatSessionSummary(
            **{
                key: str(row[key]) if key == "session_id" else row[key]
                for key in ("session_id", "agent_id", "title", "created_at", "updated_at")
            }
        )

    async def _session(self, conn, session_id, *, lock=False):
        row = await conn.fetchrow(
            "SELECT * FROM chat_sessions WHERE session_id=$1" + (" FOR UPDATE" if lock else ""),
            identifier(session_id),
        )
        if not row:
            raise AppError("CONVERSATION_NOT_FOUND", "会话不存在", 404)
        return row

    async def _messages(
        self,
        conn,
        session_id,
        *,
        run_id=None,
        before=None,
        after=None,
        limit=None,
        descending=False,
    ):
        rows = await conn.fetch(
            """SELECT m.*, c.call_id, c.agent_id, c.agent_name, c.invocation_id,
                      c.output_type, c.output,
                      ARRAY(SELECT file_id::text FROM message_files d
                            WHERE d.message_id=m.message_id ORDER BY position) AS file_ids
               FROM messages m
               LEFT JOIN agent_calls c ON c.message_id=m.message_id
               WHERE m.session_id=$1 AND ($2::uuid IS NULL OR m.run_id=$2)
                 AND ($3::bigint IS NULL OR m.sequence < $3)
                 AND ($4::bigint IS NULL OR m.sequence > $4)
               ORDER BY """
            + ("m.sequence DESC" if descending else "m.sequence")
            + " LIMIT $5",
            identifier(session_id),
            identifier(run_id) if run_id else None,
            before,
            after,
            limit,
        )
        return [
            SessionMessage(
                message_id=str(row["message_id"]),
                sequence=row["sequence"],
                role=row["role"],
                content=row["content"],
                run_id=str(row["run_id"]),
                created_at=row["created_at"],
                file_ids=tuple(row["file_ids"]),
                agent_call=ChildAgentResult(
                    id=str(row["call_id"]),
                    agent_id=row["agent_id"],
                    agent_name=row["agent_name"],
                    invocation_id=row["invocation_id"],
                    output_type=row["output_type"],
                    output=row["output"],
                )
                if row["call_id"]
                else None,
            )
            for row in rows
        ]

    async def _files(self, conn, session_id):
        rows = await conn.fetch(
            "SELECT * FROM files WHERE session_id=$1 ORDER BY created_at,file_id",
            identifier(session_id),
        )
        return [self._file(row) for row in rows]

    @staticmethod
    def _file(row):
        return SessionFile(**{**dict(row), "file_id": str(row["file_id"]),
                              "session_id": str(row["session_id"])})

    async def list_agents(self):
        async with self._connection() as conn:
            rows = await conn.fetch(
                "SELECT agent_id,name,description FROM agents ORDER BY agent_id"
            )
        return [dict(row) for row in rows]

    async def get_file(self, session_id, file_id):
        # 与 add_file 的会话行锁同步，确认原事务结束后再判断文件是否存在。
        async with self._connection(write=True) as conn:
            await self._session(conn, session_id, lock=True)
            row = await conn.fetchrow(
                "SELECT * FROM files WHERE session_id=$1 AND file_id=$2",
                identifier(session_id), identifier(file_id),
            )
            if not row:
                raise AppError("MATERIAL_NOT_FOUND", "会话材料不存在", 404)
            return self._file(row)

    async def create(self, agent_id="conversation_assistant"):
        session_id = str(uuid4())
        async with self._connection(write=True) as conn:
            await conn.execute(
                "INSERT INTO chat_sessions(session_id,agent_id,title) VALUES($1,$2,$3)",
                identifier(session_id),
                agent_id,
                "新对话",
            )
        return await self.read(session_id)

    async def list(self, agent_id, *, limit=20, cursor=None):
        stamp, last_id = None, None
        if cursor:
            try:
                if len(cursor) > 512:
                    raise ValueError
                data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                if not isinstance(data, dict) or set(data) != {
                    "v",
                    "agent_id",
                    "updated_at",
                    "session_id",
                }:
                    raise ValueError
                if any(
                    not isinstance(data[key], str)
                    for key in ("agent_id", "updated_at", "session_id")
                ):
                    raise ValueError
                if data["v"] != 2 or data["agent_id"] != agent_id:
                    raise ValueError
                stamp, last_id = (
                    datetime.fromisoformat(data["updated_at"]),
                    UUID(data["session_id"]),
                )
                if stamp.tzinfo is None:
                    raise ValueError
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise AppError("INVALID_CONVERSATION_INPUT", "会话分页游标无效", 422) from None
        async with self._connection() as conn:
            rows = await conn.fetch(
                """SELECT * FROM chat_sessions WHERE agent_id=$1
                   AND ($2::timestamptz IS NULL OR (updated_at,session_id)<($2,$3::uuid))
                   ORDER BY updated_at DESC,session_id DESC LIMIT $4""",
                agent_id,
                stamp,
                last_id,
                limit + 1,
            )
        items = [self._summary(row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit:
            last = items[-1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    dict(
                        v=2,
                        agent_id=agent_id,
                        updated_at=last.updated_at.isoformat(),
                        session_id=last.session_id,
                    )
                ).encode()
            ).decode()
        return ChatSessionListPage(items, next_cursor)

    async def read(self, session_id, *, limit=50, before_sequence=None, after_sequence=None):
        async with self._connection() as conn:
            row = await self._session(conn, session_id)
            candidates = await self._messages(
                conn,
                session_id,
                before=before_sequence,
                after=after_sequence,
                limit=limit + 1,
                descending=after_sequence is None,
            )
            page = candidates[:limit]
            if after_sequence is None:
                page.reverse()
            more = len(candidates) > limit
            active = await conn.fetchval(
                (
                    "SELECT run_id FROM runs WHERE session_id=$1 AND status "
                    "IN ('queued','running')"
                ),
                identifier(session_id),
            )
            return ChatSessionPage(
                self._summary(row),
                page,
                await self._files(conn, session_id),
                str(active) if active else None,
                row["last_sequence"],
                more,
                page[0].sequence if more and after_sequence is None else None,
                page[-1].sequence if more and after_sequence is not None else None,
            )

    async def snapshot(self, session_id, latest_message_id=None):
        async with self._connection() as conn:
            row = await self._session(conn, session_id)
            messages = await self._messages(conn, session_id)
            documents = await self._files(conn, session_id)
            continuation = json.loads(row["continuation"]) if row["continuation"] else None
            return SessionSnapshot(
                session_id,
                latest_message_id
                or next(m.message_id for m in reversed(messages) if m.role == "user"),
                tuple(messages),
                {d.file_id: d for d in documents},
                ContinuationState.model_validate(continuation["data"]) if continuation else None,
            )

    async def add_file(self, session_id, file: SessionFile):
        validate_text(file.original_name, file.source_path, file.content_path)
        if file.session_id != session_id:
            raise AppError("MATERIAL_NOT_FOUND", "会话材料不存在", 404)
        async with self._connection(write=True) as conn:
            await self._session(conn, session_id, lock=True)
            if await conn.fetchval(
                "SELECT count(*) FROM runs WHERE session_id=$1 AND status IN ('queued','running')",
                identifier(session_id),
            ):
                raise AppError("CONVERSATION_BUSY", "请等待当前操作完成", 409)
            files = await self._files(conn, session_id)
            if len(files) >= 8 or sum(f.content_chars for f in files) + file.content_chars > 100000:
                raise AppError("CONVERSATION_CAPACITY", "会话材料超过限制", 413)
            row = await conn.fetchrow(
                "INSERT INTO files(file_id,session_id,original_name,source_path,content_path,"
                "size_bytes,content_chars) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *",
                identifier(file.file_id), identifier(session_id), file.original_name,
                file.source_path, file.content_path, file.size_bytes, file.content_chars,
            )
            return self._file(row)

    async def _run(self, conn, session_id, run_id):
        row = await conn.fetchrow(
            "SELECT * FROM runs WHERE session_id=$1 AND run_id=$2",
            identifier(session_id),
            identifier(run_id),
        )
        if not row:
            raise AppError("RUN_NOT_FOUND", "会话运行不存在", 404)
        messages = await self._messages(conn, session_id, run_id=run_id)
        user = next(m for m in messages if m.role == "user")
        return SessionRun(
            run_id=str(row["run_id"]),
            request=SessionSubmission(row["client_message_id"], user.content, user.file_ids),
            status=row["status"],
            stage="已完成" if row["status"] == "succeeded" else row["error_message"] or "等待处理",
            message=next((m for m in messages if m.role == "assistant"), None),
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    async def read_run(self, session_id, run_id):
        async with self._connection() as conn:
            await self._session(conn, session_id)
            return await self._run(conn, session_id, run_id)

    @staticmethod
    def _chars(messages):
        return sum(
            len(m.content) + (len(m.agent_call.output) if m.agent_call else 0) for m in messages
        )

    async def submit(self, session_id, request, *, allow_create=True):
        validate_text(request.content, request.client_message_id)
        async with self._connection(write=True) as conn:
            row = await self._session(conn, session_id, lock=True)
            existing = await conn.fetchval(
                (
                    "SELECT run_id FROM runs WHERE session_id=$1 AND "
                    "client_message_id=$2"
                ),
                identifier(session_id),
                request.client_message_id,
            )
            if existing:
                run = await self._run(conn, session_id, str(existing))
                if run.request != request:
                    raise AppError("MESSAGE_CONFLICT", "消息标识已用于其他内容", 409)
                return SubmissionResult(run, False)
            if not allow_create:
                raise AppError("CONVERSATION_BUSY", "会话执行繁忙，请稍后重试", 503)
            if await conn.fetchval(
                (
                    "SELECT count(*) FROM runs WHERE session_id=$1 AND "
                    "status IN ('queued','running')"
                ),
                identifier(session_id),
            ):
                raise AppError("CONVERSATION_BUSY", "请等待当前操作完成", 409)
            messages = await self._messages(conn, session_id)
            if len(messages) > 98 or (
                self._chars(messages) + len(request.content) + len(CAPACITY_MESSAGE) > 1000000
            ):
                raise AppError("CONVERSATION_CAPACITY", "会话文字或消息容量已满，请新建会话", 413)
            documents = {d.file_id for d in await self._files(conn, session_id)}
            if any(doc not in documents for doc in request.file_ids):
                raise AppError("MATERIAL_NOT_FOUND", "会话材料不存在", 404)
            run_id, message_id = uuid4(), uuid4()
            await conn.execute(
                (
                    "INSERT INTO "
                    "runs(run_id,session_id,client_message_id,status) "
                    "VALUES($1,$2,$3,'queued')"
                ),
                run_id,
                identifier(session_id),
                request.client_message_id,
            )
            await conn.execute(
                (
                    "INSERT INTO "
                    "messages(message_id,session_id,run_id,sequence,role,content)"
                    " VALUES($1,$2,$3,$4,'user',$5)"
                ),
                message_id,
                identifier(session_id),
                run_id,
                row["last_sequence"] + 1,
                request.content,
            )
            for position, doc in enumerate(request.file_ids):
                await conn.execute(
                    "INSERT INTO message_files VALUES($1,$2,$3,$4)",
                    identifier(session_id),
                    message_id,
                    identifier(doc),
                    position,
                )
            title = (
                " ".join(request.content.split())[:24]
                if row["last_sequence"] == 0
                else row["title"]
            )
            await conn.execute(
                (
                    "UPDATE chat_sessions SET "
                    "last_sequence=last_sequence+1,title=$2,updated_at=clock_timestamp() "
                    "WHERE session_id=$1"
                ),
                identifier(session_id),
                title,
            )
            return SubmissionResult(await self._run(conn, session_id, str(run_id)), True)

    async def start(self, session_id, run_id):
        async with self._connection(write=True) as conn:
            await conn.execute(
                (
                    "UPDATE runs SET "
                    "status='running',started_at=clock_timestamp() WHERE session_id=$1"
                    " AND run_id=$2 AND status='queued'"
                ),
                identifier(session_id),
                identifier(run_id),
            )
            return await self._run(conn, session_id, run_id)

    async def finish(self, session_id, run_id, completion: RunCompletion):
        async with self._connection(write=True) as conn:
            row = await self._session(conn, session_id, lock=True)
            run = await self._run(conn, session_id, run_id)
            if run.status in TERMINAL:
                return run
            if completion.status not in TERMINAL:
                raise ValueError("Completion must be terminal")
            text, call, continuation = (
                completion.text,
                completion.child_call,
                completion.continuation,
            )
            status, code, error = completion.status, completion.error_code, completion.error_message
            validate_text(text, call.output if call else "")
            if (
                self._chars(await self._messages(conn, session_id))
                + len(text)
                + (len(call.output) if call else 0)
                > 1000000
            ):
                status, code, error = "failed", "CONVERSATION_CAPACITY", CAPACITY_MESSAGE
                text, call, continuation = error, None, None
            message_id = uuid4()
            await conn.execute(
                (
                    "INSERT INTO "
                    "messages(message_id,session_id,run_id,sequence,role,content)"
                    " VALUES($1,$2,$3,$4,'assistant',$5)"
                ),
                message_id,
                identifier(session_id),
                identifier(run_id),
                row["last_sequence"] + 1,
                text,
            )
            if call:
                await conn.execute(
                    "INSERT INTO agent_calls VALUES($1,$2,$3,$4,$5,$6,$7)",
                    identifier(call.id),
                    message_id,
                    call.agent_id,
                    call.agent_name,
                    call.invocation_id,
                    call.output_type,
                    call.output,
                )
            payload = None
            if continuation:
                data = continuation.model_copy(update={"question_message_id": str(message_id)})
                payload = json.dumps({"version": 1, "data": data.model_dump(mode="json")})
            await conn.execute(
                (
                    "UPDATE chat_sessions SET "
                    "last_sequence=last_sequence+1,continuation=$2::jsonb,updated_at=clock_timestamp()"
                    " WHERE session_id=$1"
                ),
                identifier(session_id),
                payload,
            )
            await conn.execute(
                (
                    "UPDATE runs SET "
                    "status=$3,error_code=$4,error_message=$5,finished_at=clock_timestamp()"
                    " WHERE session_id=$1 AND run_id=$2"
                ),
                identifier(session_id),
                identifier(run_id),
                status,
                code,
                error,
            )
            return await self._run(conn, session_id, run_id)

    async def recover_interrupted(self):
        async with self._connection() as conn:
            rows = await conn.fetch(
                "SELECT session_id,run_id FROM runs WHERE status IN "
                "('queued','running') ORDER BY session_id"
            )
        for row in rows:
            text = "服务中断，本次处理未完成，请重新提交"
            await self.finish(
                str(row["session_id"]),
                str(row["run_id"]),
                RunCompletion(
                    "failed",
                    text,
                    error_code="CONVERSATION_INTERRUPTED",
                    error_message=text,
                ),
            )
        return len(rows)

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
