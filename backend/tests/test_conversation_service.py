import asyncio
import threading
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.conversation.active_runs import ActiveRunRegistry
from app.infrastructure.conversation.postgres_store import PostgresConversationStore
from app.runtime.agent_runtime import AgentEvent, AgentExecution
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

    async def invoke(self, agent_id, payload, *, on_event=None):
        self.calls.append((agent_id, payload))
        self.entered.set()
        if self.gate:
            await self.gate.wait()
        return AgentExecution(
            "invoke",
            agent_id,
            self.results.pop(0) if self.results else ConversationTurnResult(reply="你好"),
        )


@pytest.mark.parametrize("phase,code", [
    ("intent", "STORAGE_UNAVAILABLE"), ("rollback", "STORAGE_UNAVAILABLE"),
    ("ack", None), ("unknown", "STORAGE_UNAVAILABLE"),
    ("files", "CONVERSATION_DELETE_INCOMPLETE"),
    ("receipt", "CONVERSATION_DELETE_INCOMPLETE"),
])
def test_delete_failure_boundaries_and_retry(monkeypatch, phase, code):
    async def scenario():
        service = await make_service()
        service.runtime = None
        sid = (await service.create()).session_id
        staged = service._files.stage("conversation_assistant", sid, str(uuid4()), b"docx", "body")
        paths = service._files.publish(staged)
        original_delete = service._store.delete_session
        original_inspect = service._store.inspect_deletion
        inspections = 0
        def fail_file(*args):
            raise OSError("failure")
        async def delete(*args):
            if phase != "rollback":
                await original_delete(*args)
            raise AppError("STORAGE_UNAVAILABLE", "unknown", 503)
        async def inspect(*args):
            nonlocal inspections
            inspections += 1
            if inspections > 1:
                raise AppError("STORAGE_UNAVAILABLE", "unknown", 503)
            return await original_inspect(*args)
        try:
            with monkeypatch.context() as patch:
                if phase == "intent":
                    patch.setattr(service._files, "write_deletion_intent", fail_file)
                if phase in {"rollback", "ack", "unknown"}:
                    patch.setattr(service._store, "delete_session", delete)
                if phase == "unknown":
                    patch.setattr(service._store, "inspect_deletion", inspect)
                if phase == "files":
                    patch.setattr(service._files, "discard_session", fail_file)
                if phase == "receipt":
                    patch.setattr(service._files, "discard_deletion_intent", fail_file)
                if code:
                    with pytest.raises(AppError) as error:
                        await service.delete(sid)
                    assert error.value.code == code
                else:
                    await service.delete(sid)
            exists = await original_inspect(sid) is not None
            assert exists is (phase in {"intent", "rollback"})
            if phase in {"intent", "rollback", "unknown", "files"}:
                assert (service._files.root / paths.source_path).read_bytes() == b"docx"
            if phase in {"unknown", "files", "receipt"}:
                assert service._files.read_deletion_intent(sid) is not None
            await service.delete(sid)
            assert await original_inspect(sid) is None
            assert not (service._files.root / paths.source_path).exists()
            assert service._files.read_deletion_intent(sid) is None
        finally:
            await service.aclose()
    asyncio.run(scenario())


def test_delete_rejects_terminal_run_before_task_exit():
    from app.schemas.conversation_session import RunCompletion, SessionSubmission

    async def scenario():
        service = await make_service()
        sid = (await service.create()).session_id
        run = await service._store.submit(sid, SessionSubmission("one", "hi"))
        try:
            with pytest.raises(AppError) as error:
                await service.delete(sid)
            assert error.value.code == "CONVERSATION_BUSY"
            await service._store.finish(sid, run.run.run_id, RunCompletion("succeeded", "done"))
            task = asyncio.create_task(asyncio.Event().wait())
            service._tasks[run.run.run_id] = task
            with pytest.raises(AppError) as error:
                await service.delete(sid)
            assert error.value.code == "CONVERSATION_BUSY"
            service._tasks.pop(run.run.run_id)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await service.delete(sid)
        finally:
            await service.aclose()
    asyncio.run(scenario())


def test_delete_waiter_cancel_and_shutdown_drain_worker(monkeypatch):
    async def scenario():
        service = await make_service()
        sid = (await service.create()).session_id
        entered, finish = threading.Event(), threading.Event()
        original = service._files.discard_session
        def blocked(*args):
            entered.set()
            finish.wait(5)
            original(*args)
        monkeypatch.setattr(service._files, "discard_session", blocked)
        waiter = asyncio.create_task(service.delete(sid))
        assert await asyncio.to_thread(entered.wait, 3)
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        closing = asyncio.create_task(service.aclose())
        await asyncio.sleep(0)
        assert not closing.done()
        finish.set()
        await closing
        assert not service._deletion_tasks
        assert not service._active._locks
        assert service._files.read_deletion_intent(sid) is None
    asyncio.run(scenario())


@pytest.mark.parametrize("committed", [False, True])
def test_recovery_after_each_delete_boundary(committed):
    async def scenario():
        service = await make_service()
        sid = (await service.create()).session_id
        paths = service._files.publish(service._files.stage(
            "conversation_assistant", sid, str(uuid4()), b"docx", "body"
        ))
        service._files.write_deletion_intent("conversation_assistant", sid)
        if committed:
            await service._store.delete_session(sid)
        await service.aclose()
        service = await make_service()
        await service.recover_deletions()
        assert service._files.read_deletion_intent(sid) is None
        assert (service._files.root / paths.source_path).exists() is not committed
        await service.aclose()
    asyncio.run(scenario())


def test_delete_unknown_uuid_does_not_remove_untracked_directory():
    async def scenario():
        service = await make_service()
        sid = str(uuid4())
        paths = service._files.publish(service._files.stage(
            "conversation_assistant", sid, str(uuid4()), b"keep", "body"
        ))
        await service.delete(sid)
        assert (service._files.root / paths.source_path).read_bytes() == b"keep"
        await service.aclose()
    asyncio.run(scenario())


def test_delete_busy_upload_and_race_with_submit(monkeypatch):
    async def scenario():
        service = await make_service()
        sid = (await service.create()).session_id
        service._uploads[sid] = asyncio.current_task()
        with pytest.raises(AppError) as error:
            await service.delete(sid)
        assert error.value.code == "CONVERSATION_BUSY"
        assert service._files.read_deletion_intent(sid) is None
        service._uploads.pop(sid)
        entered, finish = threading.Event(), threading.Event()
        original = service._files.write_deletion_intent
        def block(*args):
            entered.set()
            finish.wait(5)
            return original(*args)
        monkeypatch.setattr(service._files, "write_deletion_intent", block)
        deletion = asyncio.create_task(service.delete(sid))
        assert await asyncio.to_thread(entered.wait, 3)
        submit = asyncio.create_task(service.submit(
            sid, MessageCreate(client_message_id="late", content="late")
        ))
        await asyncio.sleep(0)
        assert not submit.done()
        finish.set()
        await deletion
        with pytest.raises(AppError) as missing:
            await submit
        assert missing.value.status_code == 404
        await service.aclose()
    asyncio.run(scenario())


def test_stream_snapshot_delta_reconnect_and_multiple_readers_share_one_task():
    async def scenario():
        first, finish = asyncio.Event(), asyncio.Event()

        class StreamingRuntime(Runtime):
            async def invoke(self, agent_id, payload, *, on_event=None):
                self.calls.append((agent_id, payload))
                on_event(AgentEvent("stage", "正在生成回答"))
                on_event(AgentEvent("text_delta", "你"))
                first.set()
                await finish.wait()
                on_event(AgentEvent("text_delta", "好"))
                return AgentExecution("stream", agent_id, ConversationTurnResult(reply="你好"))

        runtime = StreamingRuntime()
        service = await make_service(runtime)
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="s1", content="你好")
        )
        await asyncio.wait_for(first.wait(), 1)
        reader = await service.stream_run(session.session_id, run.run_id)
        snapshot = await anext(reader)
        assert snapshot.event == "snapshot" and snapshot.text == "你"
        assert snapshot.run.status == "running"
        assert service._active.used_bytes == len("你".encode())
        second = await service.stream_run(session.session_id, run.run_id)
        assert (await anext(second)).text == "你"
        # 关闭一个订阅不会取消任务；新订阅直接取得累计文本，不重跑模型。
        await second.aclose()
        reconnect = await service.stream_run(session.session_id, run.run_id)
        assert (await anext(reconnect)).text == "你"
        finish.set()
        events = [event async for event in reader]
        assert events[-1].event == "done" and events[-1].run.message.content == "你好"
        assert (await anext(reconnect)).event == "done"
        assert len(runtime.calls) == 1
        assert service._active.used_bytes == 0
        await reconnect.aclose()
        await service.aclose()
        assert service._active.used_bytes == 0

    asyncio.run(scenario())


def test_stream_delta_arrives_before_completion_and_cancel_wakes_reader():
    async def scenario():
        emitted, finish = asyncio.Event(), asyncio.Event()

        class StreamingRuntime(Runtime):
            async def invoke(self, agent_id, payload, *, on_event=None):
                await emitted.wait()
                on_event(AgentEvent("text_delta", "第一段"))
                await finish.wait()

        service = await make_service(StreamingRuntime())
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="s1", content="你好")
        )
        reader = await service.stream_run(session.session_id, run.run_id)
        assert (await anext(reader)).event == "snapshot"
        emitted.set()
        delta = None
        while delta is None:
            event = await asyncio.wait_for(anext(reader), 1)
            if event.event == "delta":
                delta = event
        assert delta.text == "第一段" and not service._tasks[run.run_id].done()
        await service.cancel(session.session_id, run.run_id)
        done = await asyncio.wait_for(anext(reader), 1)
        assert done.event == "done" and done.run.status == "cancelled"
        assert "第一段" not in done.run.message.content
        await reader.aclose()
        await service.aclose()

    asyncio.run(scenario())


def test_stream_capacity_failure_releases_partial_text_and_wakes_subscriber():
    async def scenario():
        class OverflowRuntime(Runtime):
            async def invoke(self, agent_id, payload, *, on_event=None):
                on_event(AgentEvent("text_delta", "x" * 30))
                on_event(AgentEvent("text_delta", "x" * 100))

        service = await make_service(
            OverflowRuntime(),
            settings=Settings(_env_file=None, conversation_transient_max_bytes=100),
        )
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="s1", content="hi")
        )
        result = await complete(service, session, run)
        assert result.status == "failed" and result.error.code == "CONVERSATION_CAPACITY"
        assert service._active.used_bytes == 0
        reader = await service.stream_run(session.session_id, run.run_id)
        assert (await anext(reader)).event == "snapshot"
        assert (await anext(reader)).event == "done"
        await reader.aclose()
        await service.aclose()

    asyncio.run(scenario())


def test_shutdown_wakes_existing_subscriber():
    async def scenario():
        service = await make_service(Runtime(gate=asyncio.Event()))
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="shutdown", content="hi")
        )
        await service.runtime.entered.wait()
        reader = await service.stream_run(session.session_id, run.run_id)
        await anext(reader)
        waiting = asyncio.create_task(anext(reader))
        await asyncio.sleep(0)
        await service.aclose()
        event = await asyncio.wait_for(waiting, 1)
        assert event.event == "done" and event.run.status == "cancelled"
        assert service._active.used_bytes == 0
        await reader.aclose()

    asyncio.run(scenario())


def test_shutdown_publishes_terminal_event_for_a_task_not_scheduled_yet():
    async def scenario():
        service = await make_service(Runtime(gate=asyncio.Event()))
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="m1", content="hi")
        )
        reader = await service.stream_run(session.session_id, run.run_id)
        assert (await anext(reader)).run.status in {"queued", "running"}
        # 没有让 _execute 获得调度；取消未启动的 task 不会执行它的 finally。
        await service.aclose()
        done = await asyncio.wait_for(anext(reader), 0.1)
        assert done.event == "done" and done.run.status == "cancelled"
        assert service._active.used_bytes == 0
        await reader.aclose()

    asyncio.run(scenario())


POSTGRES_TARGET = ("", "")


@pytest.fixture(autouse=True)
def service_target(postgres_target, monkeypatch):
    monkeypatch.setitem(globals(), "POSTGRES_TARGET", postgres_target)


async def make_service(runtime=None, *, settings=None):
    from pydantic import SecretStr

    settings = settings or Settings(_env_file=None)
    dsn, schema = POSTGRES_TARGET
    settings = settings.model_copy(update={"database_url": SecretStr(dsn)})
    store = PostgresConversationStore(settings, _schema=schema)
    await store.initialize()
    return ConversationService(
        settings,
        runtime or Runtime(),
        store=store,
        active_runs=ActiveRunRegistry(max_bytes=settings.conversation_transient_max_bytes),
    )


async def complete(service, session, run):
    await service._tasks[run.run_id]
    return await service.read_run(session.session_id, run.run_id)


def test_chat_without_upload_never_calls_child():
    async def scenario():
        runtime = Runtime()
        service = await make_service(runtime)
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="m1", content="你好")
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
        service = await make_service(runtime)
        session = await service.create()
        for index in range(2):
            run = await service.submit(
                session.session_id, MessageCreate(client_message_id=str(index), content="输入")
            )
            result = await complete(service, session, run)
            if index == 0:
                continuation = (await service._store.snapshot(session.session_id)).continuation
                assert continuation.payload == {"task": {"x": 1}}
                assert continuation.question_message_id == result.message.message_id
        assert runtime.calls[1][1]["continuation"]["payload"] == {"task": {"x": 1}}
        assert (await service._store.snapshot(session.session_id)).continuation is None
        await service.aclose()

    asyncio.run(scenario())


def test_same_client_message_id_reuses_run():
    async def scenario():
        runtime = Runtime()
        service = await make_service(runtime)
        session = await service.create()
        payload = MessageCreate(client_message_id="m1", content="你好")
        first = await service.submit(session.session_id, payload)
        second = await service.submit(session.session_id, payload)
        assert first.run_id == second.run_id
        with pytest.raises(AppError) as error:
            await service.submit(
                session.session_id, payload.model_copy(update={"content": "不同正文"})
            )
        assert error.value.status_code == 409
        await complete(service, session, first)
        assert len(runtime.calls) == 1
        assert len((await service.read(session.session_id)).messages) == 2
        await service.aclose()

    asyncio.run(scenario())


def test_cancel_releases_capacity():
    async def scenario():
        runtime = Runtime(gate=asyncio.Event())
        service = await make_service(runtime)
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="m1", content="你好")
        )
        await runtime.entered.wait()
        assert (await service.cancel(session.session_id, run.run_id)).status == "cancelled"
        assert (await service.read(session.session_id)).active_run_id is None
        runtime.gate.set()
        second = await service.submit(
            session.session_id, MessageCreate(client_message_id="m2", content="你好")
        )
        await complete(service, session, second)
        await service.aclose()

    asyncio.run(scenario())


def test_close_waits_for_tasks():
    async def scenario():
        runtime = Runtime(gate=asyncio.Event())
        service = await make_service(runtime)
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="m1", content="你好")
        )
        task = service._tasks[run.run_id]
        await service.aclose()
        assert task.done() and not service._tasks

    asyncio.run(scenario())


def test_child_result_is_displayed_without_service_dispatch():
    async def scenario():
        child = ChildAgentResult(
            id=str(uuid4()),
            agent_id="institution_review",
            agent_name="制度审核助手",
            invocation_id="child-id",
            output_type="markdown",
            output="# 原始报告",
        )
        runtime = Runtime(results=[ConversationTurnResult(reply="完成", child_call=child)])
        service = await make_service(runtime)
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="m1", content="审核")
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
        service = await make_service(runtime)
        session = await service.create()
        document = await service.upload(session.session_id, "制度.docx", docx_bytes_factory())
        assert runtime.calls == []
        monkeypatch.setattr(
            "app.services.conversation_service.parse_docx",
            lambda *a, **k: pytest.fail("聊天不能重复解析"),
        )
        run = await service.submit(
            session.session_id,
            MessageCreate(
                client_message_id="m1",
                content="你好",
                file_ids=[document.file_id],
            ),
        )
        await complete(service, session, run)
        assert len(runtime.calls) == 1
        await service.aclose()

    asyncio.run(scenario())


def test_success_is_not_overwritten_by_cancel():
    async def scenario():
        service = await make_service()
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="m1", content="你好")
        )
        await complete(service, session, run)
        assert (await service.cancel(session.session_id, run.run_id)).status == "succeeded"
        await service.aclose()

    asyncio.run(scenario())


def test_queue_capacity_is_bounded():
    async def scenario():
        service = await make_service(
            Runtime(gate=asyncio.Event()),
            settings=Settings(
                _env_file=None,
                conversation_concurrency=1,
                conversation_queue_size=0,
            ),
        )
        first, second = await service.create(), await service.create()
        await service.submit(
            first.session_id, MessageCreate(client_message_id="m1", content="你好")
        )
        with pytest.raises(AppError) as raised:
            await service.submit(
                second.session_id, MessageCreate(client_message_id="m2", content="你好")
            )
        assert raised.value.status_code == 503
        await service.aclose()

    asyncio.run(scenario())


def test_output_capacity_failure_does_not_commit_partial_result():
    async def scenario():
        child = ChildAgentResult(
            id=str(uuid4()),
            agent_id="institution_review",
            agent_name="制度审核助手",
            invocation_id="i",
            output_type="markdown",
            output="x" * 200000,
        )
        service = await make_service(
            Runtime(
                gate=asyncio.Event(),
                results=[
                    ConversationTurnResult(
                        reply="完成",
                        child_call=child,
                        continuation=ContinuationState(payload={"task": 1}),
                    )
                ],
            ),
            settings=Settings(_env_file=None, conversation_transient_max_bytes=1100),
        )
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="m1", content="你好")
        )
        async with service._store._connection(write=True) as conn:
            await conn.execute(
                "UPDATE messages SET content=repeat('x',900000) "
                "WHERE session_id=$1",
                UUID(session.session_id),
            )
        service.runtime.gate.set()
        result = await complete(service, session, run)
        assert result.status == "failed" and result.error.code == "CONVERSATION_CAPACITY"
        assert result.message.agent_call is None
        assert (await service._store.snapshot(session.session_id)).continuation is None
        assert service._active.used_bytes <= 1100
        await service.aclose()

    asyncio.run(scenario())


def test_run_timeout_has_one_terminal_message():
    async def scenario():
        service = await make_service(
            Runtime(gate=asyncio.Event()),
            settings=Settings(
                _env_file=None,
                conversation_run_timeout_seconds=0.01,
            ),
        )
        session = await service.create()
        run = await service.submit(
            session.session_id, MessageCreate(client_message_id="m1", content="你好")
        )
        result = await complete(service, session, run)
        assert result.error.code == "CONVERSATION_TIMEOUT"
        assert len((await service.read(session.session_id)).messages) == 2
        await service.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("close", [False, True])
def test_parse_cancellation_waits_for_thread_and_releases_once(monkeypatch, close):
    async def scenario():
        service = await make_service()
        session = await service.create()
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        def parse(*args, **kwargs):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5), "测试必须释放转换线程"
            return "# 正文"

        monkeypatch.setattr("app.services.conversation_service.parse_docx", parse)
        upload = asyncio.create_task(service.upload(session.session_id, "x.docx", b"input"))
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
            assert service._active.used_bytes == 0
            await service.aclose()
        assert service._parse_slots._value == 2 and upload.done()

    asyncio.run(scenario())


def test_concurrent_upload_cannot_replace_tracked_upload(monkeypatch):
    from app.schemas.conversation_turn import TurnDocument

    async def scenario():
        service = await make_service()
        session = await service.create()
        read_entered, read_release = asyncio.Event(), asyncio.Event()
        parse_entered, parse_release = asyncio.Event(), asyncio.Event()
        original = service._store.read
        first_read = True

        async def read(*args, **kwargs):
            nonlocal first_read
            if first_read:
                first_read = False
                read_entered.set()
                await read_release.wait()
            return await original(*args, **kwargs)

        async def parse(*args):
            parse_entered.set()
            await parse_release.wait()
            return TurnDocument(id=str(uuid4()), filename="x.docx", markdown="正文")

        monkeypatch.setattr(service._store, "read", read)
        monkeypatch.setattr(service, "_parse_upload", parse)
        first = asyncio.create_task(service.upload(session.session_id, "x.docx", b"x"))
        await read_entered.wait()
        second = asyncio.create_task(service.upload(session.session_id, "y.docx", b"y"))
        await asyncio.sleep(0)
        read_release.set()
        await parse_entered.wait()
        try:
            with pytest.raises(AppError) as raised:
                await asyncio.wait_for(asyncio.shield(second), 0.5)
            assert raised.value.status_code == 409
            assert service._uploads[session.session_id] is first
        finally:
            parse_release.set()
            await asyncio.gather(first, second, return_exceptions=True)
            await service.aclose()

    asyncio.run(scenario())


def test_shutdown_cancels_upload_waiting_for_session_read(monkeypatch):
    async def scenario():
        service = await make_service()
        session = await service.create()
        entered = asyncio.Event()
        release = asyncio.Event()
        page = await service._store.read(session.session_id)
        parse_calls = []

        async def read(*args, **kwargs):
            entered.set()
            await release.wait()
            return page

        async def parse(*args):
            parse_calls.append(args)
            raise AssertionError("关闭后不得启动解析")

        monkeypatch.setattr(service._store, "read", read)
        monkeypatch.setattr(service, "_parse_upload", parse)
        upload = asyncio.create_task(service.upload(session.session_id, "x.docx", b"x"))
        await entered.wait()
        try:
            await service.aclose()
            release.set()
            result = (await asyncio.gather(upload, return_exceptions=True))[0]
            assert isinstance(result, asyncio.CancelledError)
            assert not parse_calls
            assert not service._uploads and service._active.used_bytes == 0
        finally:
            release.set()
            await asyncio.gather(upload, return_exceptions=True)
            await service.aclose()

    asyncio.run(scenario())


def test_lost_commit_ack_is_reconciled_without_model_reexecution(monkeypatch):
    async def scenario():
        service = await make_service()
        session = await service.create()
        original = service._store.submit

        async def commit_then_lose_ack(*args, **kwargs):
            await original(*args, **kwargs)
            raise AppError("STORAGE_UNAVAILABLE", "提交结果未确认", 503)

        payload = MessageCreate(client_message_id="lost-commit", content="不可重做")
        monkeypatch.setattr(service._store, "submit", commit_then_lose_ack)
        with pytest.raises(AppError):
            await service.submit(session.session_id, payload)
        monkeypatch.setattr(service._store, "submit", original)
        try:
            recovered = await service.submit(session.session_id, payload)
            assert recovered.status == "failed"
            assert recovered.error.code == "CONVERSATION_INTERRUPTED"
            assert not service.runtime.calls
            assert (await service.read(session.session_id)).active_run_id is None
            later = await service.submit(
                session.session_id, MessageCreate(client_message_id="later", content="下一条")
            )
            await complete(service, session, later)
            assert len(service.runtime.calls) == 1
        finally:
            await service.aclose()

    asyncio.run(scenario())


def test_shutdown_does_not_schedule_pending_message_submission(monkeypatch):
    async def scenario():
        runtime = Runtime()
        service = await make_service(runtime)
        session = await service.create()
        entered, release = asyncio.Event(), asyncio.Event()
        original = service._store.submit

        async def submit(*args, **kwargs):
            result = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return result

        monkeypatch.setattr(service._store, "submit", submit)
        request = asyncio.create_task(service.submit(
            session.session_id, MessageCreate(client_message_id="shutdown", content="你好")
        ))
        await entered.wait()
        try:
            await service.aclose()
            release.set()
            result = (await asyncio.gather(request, return_exceptions=True))[0]
            assert isinstance(result, asyncio.CancelledError)
            assert not service._tasks and not service._run_sessions
            assert not runtime.calls
            assert service._admission._value == (
                service.settings.conversation_concurrency + service.settings.conversation_queue_size
            )
        finally:
            release.set()
            await asyncio.gather(request, return_exceptions=True)
            await service.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["rollback", "lost_ack", "unknown"])
def test_file_commit_failure_never_removes_referenced_file(
    docx_bytes_factory, monkeypatch, failure
):
    async def scenario():
        service = await make_service()
        session = await service.create()
        original = service._store.add_file
        captured = []

        async def failing(session_id, file):
            captured.append(file)
            if failure == "lost_ack":
                await original(session_id, file)
            raise AppError("STORAGE_UNAVAILABLE", "保存结果未确认", 503)

        async def unavailable(*args):
            raise AppError("STORAGE_UNAVAILABLE", "核实失败", 503)

        monkeypatch.setattr(service._store, "add_file", failing)
        if failure == "unknown":
            monkeypatch.setattr(service._store, "get_file", unavailable)
        try:
            with pytest.raises(AppError):
                await service.upload(session.session_id, "材料.docx", docx_bytes_factory())
            file = captured[0]
            assert (service._files.root / file.content_path).exists() == (failure != "rollback")
            assert len((await service.read(session.session_id)).files) == (failure == "lost_ack")
            assert not list((service._files.root / ".staging").glob("*"))
        finally:
            await service.aclose()

    asyncio.run(scenario())


def test_restart_reads_saved_markdown_without_parsing_again(docx_bytes_factory, monkeypatch):
    async def scenario():
        service = await make_service()
        session = await service.create()
        raw = docx_bytes_factory(body="第一条 应保留完整材料")
        file = await service.upload(session.session_id, "../../材料.docx", raw)
        saved = await service._store.get_file(session.session_id, file.file_id)
        original = service._files.read_markdown(saved.content_path)
        assert (service._files.root / saved.source_path).read_bytes() == raw
        assert file.original_name == "材料.docx"
        assert set(file.model_dump()) == {
            "file_id", "original_name", "size_bytes", "content_chars", "created_at",
        }
        await service.aclose()

        def no_parse(*args, **kwargs):
            raise AssertionError("已保存材料不得重复解析")

        monkeypatch.setattr("app.services.conversation_service.parse_docx", no_parse)
        service = await make_service()
        try:
            run = await service.submit(
                session.session_id,
                MessageCreate(
                    client_message_id="read", content="阅读材料", file_ids=[file.file_id]
                ),
            )
            result = await complete(service, session, run)
            assert result.status == "succeeded"
            material = service.runtime.calls[0][1]["documents"][0]
            assert material["id"] == file.file_id and material["markdown"] == original
            (service._files.root / saved.content_path).write_text("被改动", encoding="utf-8")
            run = await service.submit(
                session.session_id, MessageCreate(client_message_id="bad", content="继续"),
            )
            result = await complete(service, session, run)
            assert result.error.code == "FILE_UNAVAILABLE"
            assert len(service.runtime.calls) == 1
        finally:
            await service.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["stage", "publish"])
def test_cancel_waits_for_file_thread_and_cleans_only_its_upload(
    docx_bytes_factory, monkeypatch, operation,
):
    async def scenario():
        service = await make_service()
        session = await service.create()
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original = getattr(service._files, operation)

        def blocked(*args):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
            return original(*args)

        monkeypatch.setattr(service._files, operation, blocked)
        upload = asyncio.create_task(
            service.upload(session.session_id, "x.docx", docx_bytes_factory())
        )
        await asyncio.wait_for(entered.wait(), 5)
        upload.cancel()
        await asyncio.sleep(0)
        upload.cancel()
        try:
            assert not upload.done()
            assert service._uploads[session.session_id] is upload
            assert service._parse_slots._value == 1
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await upload
        try:
            assert not (await service.read(session.session_id)).files
            assert not list(service._files.root.rglob("source.docx"))
            assert service._active.used_bytes == 0
            assert service._parse_slots._value == 2
        finally:
            await service.aclose()

    asyncio.run(scenario())
