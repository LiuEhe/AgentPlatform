import asyncio
import threading

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.conversation.in_memory_store import InMemoryConversationStore
from app.runtime.agent_runtime import AgentExecution
from app.schemas.conversation import MessageCreate
from app.schemas.conversation_turn import (
    ChildAgentResult,
    ContinuationState,
    ConversationTurnResult,
)
from app.services.conversation_service import ConversationService


class Runtime:
    def __init__(self, results=None, gate=None):
        self.results = list(results or [])
        self.calls = []
        self.gate = gate
        self.entered = asyncio.Event()

    async def invoke(self, agent_id, payload):
        self.calls.append((agent_id, payload))
        self.entered.set()
        if self.gate:
            await self.gate.wait()
        return AgentExecution(
            "invoke",
            agent_id,
            self.results.pop(0) if self.results else ConversationTurnResult(reply="你好"),
        )


def make_service(runtime=None, *, settings=None, clock=lambda: 0.0):
    settings = settings or Settings(_env_file=None)
    store = InMemoryConversationStore(
        idle_seconds=settings.conversation_idle_seconds,
        lifetime_seconds=settings.conversation_lifetime_seconds,
        max_sessions=settings.conversation_max_sessions,
        max_bytes=settings.conversation_max_bytes,
        clock=clock,
    )
    return ConversationService(settings, runtime or Runtime(), store=store)


async def complete(service, session, run):
    await service._tasks[run.id]
    return await service.read_run(session.id, run.id)


def test_chat_without_upload_never_calls_child():
    async def scenario():
        runtime = Runtime()
        service = make_service(runtime)
        session = await service.create()
        run = await service.submit(
            session.id, MessageCreate(client_message_id="m1", content="你好")
        )
        result = await complete(service, session, run)
        assert result.status == "succeeded" and result.message.content == "你好"
        assert [call[0] for call in runtime.calls] == ["conversation_assistant"]
        await service.aclose()

    asyncio.run(scenario())


def test_continuation_is_opaque_and_linked_to_saved_message():
    async def scenario():
        runtime = Runtime(
            results=[
                ConversationTurnResult(
                    reply="请补充", continuation=ContinuationState(payload={"task": {"x": 1}})
                ),
                ConversationTurnResult(reply="完成"),
            ]
        )
        service = make_service(runtime)
        session = await service.create()
        for index in range(2):
            run = await service.submit(
                session.id, MessageCreate(client_message_id=str(index), content="输入")
            )
            result = await complete(service, session, run)
            if index == 0:
                continuation = service._store.record(session.id).continuation
                assert continuation.payload == {"task": {"x": 1}}
                assert continuation.question_message_id == result.message.id
        assert runtime.calls[1][1]["continuation"]["payload"] == {"task": {"x": 1}}
        assert service._store.record(session.id).continuation is None
        await service.aclose()

    asyncio.run(scenario())


def test_same_client_message_id_reuses_run():
    async def scenario():
        runtime = Runtime()
        service = make_service(runtime)
        session = await service.create()
        payload = MessageCreate(client_message_id="m1", content="你好")
        first = await service.submit(session.id, payload)
        second = await service.submit(session.id, payload)
        assert first.id == second.id
        with pytest.raises(AppError) as error:
            await service.submit(session.id, payload.model_copy(update={"content": "不同正文"}))
        assert error.value.status_code == 409
        await complete(service, session, first)
        assert len(runtime.calls) == 1
        assert len((await service.read(session.id)).messages) == 2
        await service.aclose()

    asyncio.run(scenario())


def test_cancel_releases_capacity():
    async def scenario():
        runtime = Runtime(gate=asyncio.Event())
        service = make_service(runtime)
        session = await service.create()
        run = await service.submit(
            session.id, MessageCreate(client_message_id="m1", content="你好")
        )
        await runtime.entered.wait()
        assert (await service.cancel(session.id, run.id)).status == "cancelled"
        assert (await service.read(session.id)).active_run_id is None
        runtime.gate.set()
        second = await service.submit(
            session.id, MessageCreate(client_message_id="m2", content="你好")
        )
        await complete(service, session, second)
        await service.aclose()

    asyncio.run(scenario())


def test_close_waits_for_tasks():
    async def scenario():
        runtime = Runtime(gate=asyncio.Event())
        service = make_service(runtime)
        session = await service.create()
        run = await service.submit(
            session.id, MessageCreate(client_message_id="m1", content="你好")
        )
        task = service._tasks[run.id]
        await service.aclose()
        assert task.done() and service._store.peek(session.id) is None

    asyncio.run(scenario())


def test_child_result_is_displayed_without_service_dispatch():
    async def scenario():
        child = ChildAgentResult(
            id="c",
            agent_id="institution_review",
            agent_name="制度审核助手",
            invocation_id="child-id",
            output_type="markdown",
            output="# 原始报告",
        )
        runtime = Runtime(results=[ConversationTurnResult(reply="完成", child_call=child)])
        service = make_service(runtime)
        session = await service.create()
        run = await service.submit(
            session.id, MessageCreate(client_message_id="m1", content="审核")
        )
        result = await complete(service, session, run)
        assert result.message.agent_call.output == "# 原始报告"
        assert result.message.agent_call.invocation_id == "child-id"
        assert result.message.agent_call.status == "succeeded"
        assert [c[0] for c in runtime.calls] == ["conversation_assistant"]
        await service.aclose()

    asyncio.run(scenario())


def test_uploaded_doc_then_smalltalk_never_reparses_or_calls_child(docx_bytes_factory, monkeypatch):
    async def scenario():
        runtime = Runtime()
        service = make_service(runtime)
        session = await service.create()
        document = await service.upload(session.id, "制度.docx", docx_bytes_factory())
        assert runtime.calls == []
        monkeypatch.setattr(
            "app.services.conversation_service.parse_docx",
            lambda *a, **k: pytest.fail("聊天不能重复解析"),
        )
        run = await service.submit(
            session.id,
            MessageCreate(
                client_message_id="m1",
                content="你好",
                document_ids=[document.id],
            ),
        )
        await complete(service, session, run)
        assert len(runtime.calls) == 1
        await service.aclose()

    asyncio.run(scenario())


def test_success_is_not_overwritten_by_cancel():
    async def scenario():
        service = make_service()
        session = await service.create()
        run = await service.submit(
            session.id, MessageCreate(client_message_id="m1", content="你好")
        )
        await complete(service, session, run)
        assert (await service.cancel(session.id, run.id)).status == "succeeded"
        await service.aclose()

    asyncio.run(scenario())


def test_queue_capacity_is_bounded():
    async def scenario():
        service = make_service(
            Runtime(gate=asyncio.Event()),
            settings=Settings(
                _env_file=None,
                conversation_concurrency=1,
                conversation_queue_size=0,
            ),
        )
        first, second = await service.create(), await service.create()
        await service.submit(first.id, MessageCreate(client_message_id="m1", content="你好"))
        with pytest.raises(AppError) as raised:
            await service.submit(second.id, MessageCreate(client_message_id="m2", content="你好"))
        assert raised.value.status_code == 503
        await service.aclose()

    asyncio.run(scenario())


def test_output_capacity_failure_does_not_commit_partial_result():
    async def scenario():
        child = ChildAgentResult(
            id="c",
            agent_id="institution_review",
            agent_name="制度审核助手",
            invocation_id="i",
            output_type="markdown",
            output="x" * 4000,
        )
        service = make_service(
            Runtime(
                results=[
                    ConversationTurnResult(
                        reply="完成",
                        child_call=child,
                        continuation=ContinuationState(payload={"task": 1}),
                    )
                ]
            ),
            settings=Settings(_env_file=None, conversation_max_bytes=1100),
        )
        session = await service.create()
        run = await service.submit(
            session.id, MessageCreate(client_message_id="m1", content="你好")
        )
        result = await complete(service, session, run)
        assert result.status == "failed" and result.error.code == "CONVERSATION_CAPACITY"
        assert result.message.agent_call is None
        assert service._store.record(session.id).continuation is None
        assert service._store.used_bytes <= 1100
        await service.aclose()

    asyncio.run(scenario())


def test_run_timeout_has_one_terminal_message():
    async def scenario():
        service = make_service(
            Runtime(gate=asyncio.Event()),
            settings=Settings(
                _env_file=None,
                conversation_run_timeout_seconds=0.01,
            ),
        )
        session = await service.create()
        run = await service.submit(
            session.id, MessageCreate(client_message_id="m1", content="你好")
        )
        result = await complete(service, session, run)
        assert result.error.code == "CONVERSATION_TIMEOUT"
        assert len((await service.read(session.id)).messages) == 2
        await service.aclose()

    asyncio.run(scenario())


def test_expired_active_session_can_be_cancelled_and_reclaimed():
    async def scenario():
        now = [0.0]
        runtime = Runtime(gate=asyncio.Event())
        service = make_service(runtime, clock=lambda: now[0])
        session = await service.create()
        run = await service.submit(
            session.id, MessageCreate(client_message_id="m1", content="你好")
        )
        record = service._store.record(session.id)
        await runtime.entered.wait()
        now[0] = 28801
        await service._expire_sessions()
        assert record.runs[run.id].status == "cancelled"
        assert service._store.peek(session.id) is None and service._store.used_bytes == 0
        assert service._slots._value == 3
        await service.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("close", [False, True])
def test_parse_cancellation_waits_for_thread_and_releases_once(monkeypatch, close):
    async def scenario():
        service = make_service()
        session = await service.create()
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        def parse(*args, **kwargs):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5), "测试必须释放转换线程"
            return "# 正文"

        monkeypatch.setattr("app.services.conversation_service.parse_docx", parse)
        upload = asyncio.create_task(service.upload(session.id, "x.docx", b"input"))
        await entered.wait()
        stopping = asyncio.create_task(service.aclose()) if close else upload
        if not close:
            upload.cancel()
        await asyncio.sleep(0)
        try:
            assert not stopping.done()
            assert service._parse_slots._value == 1
            if not close:
                upload.cancel()
                await asyncio.sleep(0)
                assert not upload.done() and service._parse_slots._value == 1
        finally:
            release.set()
        if close:
            await stopping
        else:
            with pytest.raises(asyncio.CancelledError):
                await upload
            assert service._store.used_bytes == 0
            await service.aclose()
        assert service._parse_slots._value == 2 and upload.done()

    asyncio.run(scenario())
