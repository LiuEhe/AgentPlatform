import asyncio
import os
import sys
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from docx import Document

from app.schemas.conversation_turn import (
    ConversationTurnInput,
    ConversationTurnResources,
    ConversationTurnResult,
    MaterialDescriptor,
    MaterialReference,
    TurnMaterial,
    TurnMessage,
)


def pytest_configure():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(autouse=True)
def isolate_external_settings(monkeypatch, tmp_path):
    import os

    for key in tuple(os.environ):
        if key.startswith(("CONVERSATION_", "LANGFUSE_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_PROMPTS_ENABLED", "false")
    monkeypatch.setenv("DOCUMENTS_DIR", str(tmp_path / "documents"))
    for key in (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "RAGFLOW_BASE_URL",
        "RAGFLOW_API_KEY",
        "RAGFLOW_DATASET_ID",
        "INSTITUTION_REVIEW_CONCURRENCY",
        "DOCUMENT_EXPORT_TIMEOUT_SECONDS",
        "DOCUMENT_EXPORT_CONCURRENCY",
        "DOCUMENT_EXPORT_MAX_CHARS",
        "DOCUMENT_EXPORT_MAX_BODY_BYTES",
        "DOCUMENT_EXPORT_MAX_OUTPUT_BYTES",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def postgres_target():
    from app.core.config import Settings
    from app.infrastructure.database import BaseDatabase
    from scripts.manage_users import initialize_v4

    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn or urlsplit(dsn).path != "/agent_platform_test":
        pytest.fail("真实数据库测试需要显式 TEST_DATABASE_URL，库名必须为 agent_platform_test")
    schema = "history_test_" + uuid4().hex
    settings = Settings(_env_file=None, database_url=dsn)

    async def prepare():
        async with BaseDatabase.maintenance(settings) as db:
            await db.execute(f'CREATE SCHEMA "{schema}"')
        await initialize_v4(settings, "test-pass123", schema=schema)
        async with BaseDatabase.maintenance(settings, schema=schema) as db:
            uid = await db.fetchval("SELECT user_id FROM users WHERE username='admin'")
            await db.execute(
                "INSERT INTO auth_sessions(auth_session_id,user_id,token_hash,csrf_token,"
                "expires_at) VALUES($1,$2,$3,'test-csrf',now()+interval '1 day')",
                uuid4(), uid, bytes(32),
            )

    async def cleanup():
        async with BaseDatabase.maintenance(settings) as db:
            # 本次生成的随机测试schema，不清理应用/public schema。
            await db.execute(f'DROP SCHEMA "{schema}" CASCADE')

    asyncio.run(prepare())
    yield dsn, schema
    asyncio.run(cleanup())


@pytest.fixture
def fake_model_factory():
    class FakeModel:
        def __init__(self, handler=None):
            self.calls = []
            self.handler = handler

        async def call(self, schema, messages):
            self.calls.append((schema, messages))
            if self.handler:
                return await self.handler(schema, messages)
            return schema() if schema else "未发现术语问题，无需基于本次检查修改。"

        def with_structured_output(self, schema):
            async def invoke(messages):
                return await self.call(schema, messages)

            return SimpleNamespace(ainvoke=invoke)

        async def ainvoke(self, messages):
            return await self.call(None, messages)

    return FakeModel


@pytest.fixture
def docx_bytes_factory():
    def make(*, title="草稿", body="第一条 正文"):
        doc = Document()
        doc.add_heading(title, level=1)
        for line in body.splitlines():
            doc.add_paragraph(line)
        buffer = BytesIO()
        doc.save(buffer)
        return buffer.getvalue()

    return make


@pytest.fixture
def turn_factory():
    def make(*, role="user", content="你好", documents=(), session_id=None,
             checkpoint_id=None, sequence=1):
        return ConversationTurnInput(
            agent_id="conversation_assistant", session_id=session_id or str(uuid4()),
            run_id=str(uuid4()), checkpoint_id=checkpoint_id,
            message=TurnMessage(id=f"m{sequence}", sequence=sequence, role=role, content=content,
                                document_ids=tuple(d.id for d in documents)),
            assistant_message_id=f"m{sequence + 1}", assistant_sequence=sequence + 1,
            material_catalog=tuple(MaterialDescriptor(
                ref=MaterialReference(kind="document", id=d.id),
                title=d.filename, chars=len(d.markdown),
            ) for d in documents),
        )

    return make


def turn_resources(turn, documents=(), *, sources=None):
    from app.core.errors import AppError
    values = {("document", d.id): (d.filename, d.markdown) for d in documents}
    values[("user_message", turn.message.id)] = ("粘贴正文", turn.message.content)
    values.update(sources or {})

    async def read(refs):
        if any((ref.kind, ref.id) not in values for ref in refs):
            raise AppError("MATERIAL_NOT_FOUND", "会话材料不存在", 404)
        return tuple(TurnMaterial(ref=ref, title=values[(ref.kind, ref.id)][0],
                                  content=values[(ref.kind, ref.id)][1]) for ref in refs)
    return ConversationTurnResources(read)


def runtime_result(payload, reply="你好", child_call=None):
    """受控运行时替身明确生成新契约；不用于生产或真正记忆验收。"""
    return ConversationTurnResult(
        reply=reply, child_call=child_call, checkpoint_id="test-checkpoint-" + uuid4().hex,
        assistant_message_id=payload["assistant_message_id"],
        assistant_sequence=payload["assistant_sequence"],
    )


async def invoke_graph(graph, turn, documents=(), *, sources=None):
    from langchain_core.messages import HumanMessage

    from app.agents.conversation_assistant.schemas import ConversationExecutionContext
    from app.schemas.conversation_turn import conversation_thread_id
    config = {"configurable": {"thread_id": conversation_thread_id(turn.agent_id, turn.session_id)}}
    if turn.checkpoint_id:
        config["configurable"]["checkpoint_id"] = turn.checkpoint_id
    return await graph.ainvoke(
        {"messages": [HumanMessage(id=turn.message.id, content=turn.message.content,
                     additional_kwargs={"sequence": turn.message.sequence, "run_id": turn.run_id,
                                        "document_ids": list(turn.message.document_ids)})]},
        config=config, context=ConversationExecutionContext(
            turn, turn_resources(turn, documents, sources=sources).read_materials,
        ), durability="sync",
    )


async def finish_success(store, actor, session_id, run_id, text, *, child_call=None):
    """仓储事务测试提供不透明定位符；真实 saver 由专门集成用例验证。"""
    from app.schemas.conversation_session import RunCompletion
    turn = await store.load_turn(actor, session_id, run_id, assistant_message_id=str(uuid4()))
    return await store.finish(actor, session_id, run_id, RunCompletion(
        "succeeded", text, child_call=child_call, assistant_message_id=turn.assistant_message_id,
        assistant_sequence=turn.assistant_sequence, expected_checkpoint_id=turn.checkpoint_id,
        memory_checkpoint_id="test-checkpoint-" + uuid4().hex,
    ))


@pytest.fixture(autouse=True)
def wire_application_database(monkeypatch, request):
    if "create_app" not in request.module.__dict__ or getattr(request.module, "AUTH_TEST", False):
        return
    postgres_target = request.getfixturevalue("postgres_target")
    from pydantic import SecretStr

    import app.main as main_module
    from app.infrastructure.database import Database

    dsn, schema = postgres_target

    def make_database(settings, **kwargs):
        settings = settings.model_copy(update={"database_url": SecretStr(dsn)})
        return Database(settings, schema=schema, **kwargs)

    monkeypatch.setattr(main_module, "Database", make_database)
    from fastapi.testclient import TestClient
    original_enter = TestClient.__enter__
    def authenticated_enter(client):
        original_enter(client)
        response = client.post(
            client.app.state.settings.api_prefix + "/auth/login",
            json={"username": "admin", "password": "test-pass123"},
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.status_code == 200, response.text
        context = response.json()
        client.headers.update(
            {
                "Origin": "http://localhost:5173",
                "X-Auth-Session-ID": context["auth_session_id"],
                "X-CSRF-Token": context["csrf_token"],
            }
        )
        return client
    monkeypatch.setattr(TestClient, "__enter__", authenticated_enter)



@pytest.fixture
def actor(postgres_target):
    dsn, schema = postgres_target
    async def load():
        from app.core.config import Settings
        from app.infrastructure.database import BaseDatabase
        from app.infrastructure.identity.postgres_store import LIVE, _context

        async with BaseDatabase.maintenance(
            Settings(_env_file=None, database_url=dsn), schema=schema
        ) as db:
            return _context(await db.fetchrow(LIVE + "AND s.token_hash=$1", bytes(32)))
    return asyncio.run(load())
