"""官方检查点资源边界与专用 PostgreSQL schema 验收。"""

import asyncio
import os
import sys
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.database import BaseDatabase


def test_event_loop_factory_supports_official_driver_and_uvicorn():
    from uvicorn import Config

    from app.infrastructure.conversation.checkpoints import event_loop_factory

    factory = Config(
        "app.main:create_app", loop="app.infrastructure.conversation.checkpoints:event_loop_factory"
    ).get_loop_factory()
    assert factory is event_loop_factory
    loop = factory()
    try:
        if sys.platform == "win32":
            assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


@pytest.fixture
def empty_postgres_schema():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn or urlsplit(dsn).path != "/agent_platform_test":
        pytest.fail("真实数据库测试需要显式 TEST_DATABASE_URL，库名必须为 agent_platform_test")
    schema = "history_test_" + uuid4().hex
    settings = Settings(_env_file=None, database_url=dsn)

    async def execute(sql):
        async with BaseDatabase.maintenance(settings) as db:
            await db.execute(sql)

    asyncio.run(execute(f'CREATE SCHEMA "{schema}"'))
    try:
        yield settings, schema
    finally:
        asyncio.run(execute(f'DROP SCHEMA "{schema}" CASCADE'))


@pytest.mark.parametrize("schema", ["public; DROP TABLE users", "other", "", "history_test_x"])
def test_checkpoint_resources_reject_invalid_schema(schema):
    from app.infrastructure.conversation.checkpoints import CheckpointResources

    with pytest.raises(ValueError):
        CheckpointResources(Settings(_env_file=None), schema=schema)


def test_open_requires_database_url():
    from app.infrastructure.conversation.checkpoints import CheckpointResources

    async def scenario():
        resources = CheckpointResources(Settings(_env_file=None))
        with pytest.raises(AppError) as error:
            await resources.open()
        assert error.value.code == "STORAGE_UNAVAILABLE"
        await resources.aclose()
        await resources.aclose()

    asyncio.run(scenario())


def test_official_setup_is_schema_scoped(empty_postgres_schema):
    from app.infrastructure.conversation.checkpoints import CheckpointResources

    settings, schema = empty_postgres_schema

    async def scenario():
        resources = CheckpointResources(settings, schema=schema)
        await resources.open()
        try:
            await resources.setup()
            await resources.assert_ready()
            async with BaseDatabase.maintenance(settings, schema=schema) as db:
                tables = await db.fetch(
                    "SELECT tablename FROM pg_tables WHERE schemaname=$1", schema,
                )
            assert {row[0] for row in tables} == {
                "checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations",
            }
        finally:
            await resources.aclose()

    asyncio.run(scenario())


def test_assert_ready_never_creates_tables(empty_postgres_schema):
    from app.infrastructure.conversation.checkpoints import CheckpointResources

    settings, schema = empty_postgres_schema

    async def scenario():
        resources = CheckpointResources(settings, schema=schema)
        await resources.open()
        try:
            with pytest.raises(AppError) as error:
                await resources.assert_ready()
            assert error.value.code == "STORAGE_SCHEMA_INVALID"
            async with BaseDatabase.maintenance(settings, schema=schema) as db:
                assert not await db.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname=$1)", schema,
                )
        finally:
            await resources.aclose()

    asyncio.run(scenario())


def test_official_thread_delete_preserves_other_threads(empty_postgres_schema):
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    from app.infrastructure.conversation.checkpoints import CheckpointResources

    class State(TypedDict):
        value: str

    settings, schema = empty_postgres_schema

    async def scenario():
        resources = CheckpointResources(settings, schema=schema)
        await resources.open()
        try:
            await resources.setup()
            builder = StateGraph(State)
            builder.add_node("echo", lambda state: state)
            builder.add_edge(START, "echo")
            builder.add_edge("echo", END)
            graph = builder.compile(checkpointer=resources.saver)
            a = {"configurable": {"thread_id": "assistant_a:session"}}
            b = {"configurable": {"thread_id": "assistant_b:session"}}
            await graph.ainvoke({"value": "a"}, a, durability="sync")
            await graph.ainvoke({"value": "b"}, b, durability="sync")
            await resources.delete_thread("assistant_a:session")
            assert await resources.saver.aget_tuple(a) is None
            assert (await graph.aget_state(b)).values["value"] == "b"
        finally:
            await resources.aclose()

    asyncio.run(scenario())


def test_initialize_retries_after_business_rollback(empty_postgres_schema, monkeypatch):
    from scripts import manage_users

    settings, schema = empty_postgres_schema

    async def scenario():
        original = manage_users.SQL_ROOT

        class BrokenSQL:
            def __truediv__(self, name):
                return self

            def read_text(self, **kwargs):
                return "CREATE TABLE failed_business(id int); SELECT 1 / 0;"

        monkeypatch.setattr(manage_users, "SQL_ROOT", BrokenSQL())
        with pytest.raises(AppError):
            await manage_users.initialize_v4(settings, "test-pass123", schema=schema)
        async with BaseDatabase.maintenance(settings, schema=schema) as db:
            assert await db.fetchval("SELECT to_regclass('checkpoints')") is not None
            assert await db.fetchval("SELECT to_regclass('failed_business')") is None
        monkeypatch.setattr(manage_users, "SQL_ROOT", original)
        await manage_users.initialize_v4(settings, "test-pass123", schema=schema)
        async with BaseDatabase.maintenance(settings, schema=schema) as db:
            assert await db.fetchval("SELECT version FROM chat_schema_version") == 4
            assert await db.fetchval("SELECT count(*) FROM users") == 1
        with pytest.raises(ValueError):
            await manage_users.initialize_v4(settings, "test-pass123", schema=schema)

    asyncio.run(scenario())


def test_two_assistant_graphs_share_saver_and_summary_without_policy_leak(empty_postgres_schema):
    import operator
    from types import SimpleNamespace
    from typing import Annotated

    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    from app.infrastructure.conversation.checkpoints import CheckpointResources
    from app.nodes.llm.memory import MemoryPolicy, needs_summary, summarize_history
    from app.nodes.llm.prompts import PromptSpec
    from app.schemas.conversation_turn import conversation_thread_id

    class State(TypedDict):
        messages: Annotated[list, operator.add]
        summary: str

    class Model:
        def with_structured_output(self, schema):
            async def invoke(messages):
                return {"text": messages[0][1]}
            return SimpleNamespace(ainvoke=invoke)

    def build(saver, policy, label):
        async def remember(state):
            if not needs_summary(state["messages"], policy=policy):
                return {}
            result = await summarize_history(
                Model(),
                state["messages"],
                previous_summary="",
                covered_sequence=0,
                policy=policy,
                prompt=PromptSpec(label, (("system", label), ("human", "{content}"))),
            )
            return {"summary": result.text}

        graph = StateGraph(State)
        graph.add_node("remember", remember)
        graph.add_edge(START, "remember")
        graph.add_edge("remember", END)
        return graph.compile(checkpointer=saver)

    settings, schema = empty_postgres_schema

    async def scenario():
        resources = CheckpointResources(settings, schema=schema)
        await resources.open()
        try:
            await resources.setup()
            sid = str(uuid4())
            a, b = [conversation_thread_id(agent, sid) for agent in ("assistant_a", "assistant_b")]
            ga = build(resources.saver, MemoryPolicy(trigger_messages=0), "摘要甲")
            gb = build(resources.saver, MemoryPolicy(trigger_messages=10), "摘要乙")
            ca, cb = [{"configurable": {"thread_id": thread}} for thread in (a, b)]
            message = HumanMessage(
                id="m1", content="事实", additional_kwargs={"sequence": 1, "run_id": "r1"}
            )
            await asyncio.gather(
                ga.ainvoke({"messages": [message]}, ca, durability="sync"),
                gb.ainvoke({"messages": [message]}, cb, durability="sync"),
            )
            sa, sb = await ga.aget_state(ca), await gb.aget_state(cb)
            assert sa.values["summary"] == "摘要甲"
            assert not sb.values.get("summary")
            assert (
                sa.config["configurable"]["checkpoint_id"]
                != sb.config["configurable"]["checkpoint_id"]
            )
            await resources.delete_thread(a)
            assert await resources.saver.aget_tuple(ca) is None
            assert (await gb.aget_state(cb)).values["messages"][0].id == "m1"
        finally:
            await resources.aclose()

    asyncio.run(scenario())
