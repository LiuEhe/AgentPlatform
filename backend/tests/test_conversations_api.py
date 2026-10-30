import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.schemas.conversation import MessageCreate, RunEvent, RunView


def settings(**updates):
    return Settings(_env_file=None, llm_model="test", llm_api_key="test", **updates)


def test_create_and_chat_without_multipart(monkeypatch, fake_model_factory):
    async def handler(schema, messages):
        return {"intent": "general_chat", "action": "answer"} if schema else "你好，随时可以聊。"

    monkeypatch.setattr("app.main.create_llm_service", lambda _: fake_model_factory(handler))
    with TestClient(create_app(settings())) as client:
        created = client.post("/api/v1/sessions")
        assert created.status_code == 201
        id = created.json()["session_id"]
        sent = client.post(
            f"/api/v1/sessions/{id}/messages",
            json={"client_message_id": "m1", "content": "你好"},
        )
        assert sent.status_code == 202
        run_id = sent.json()["run_id"]
        for _ in range(100):
            run = client.get(f"/api/v1/sessions/{id}/runs/{run_id}").json()
            if run["status"] in {"succeeded", "failed"}:
                break
        assert run["status"] == "succeeded"
        assert run["message"]["agent_call"] is None
        assert run["message"]["content"] == "你好，随时可以聊。"


def test_no_model_allows_session_but_not_execution():
    with TestClient(
        create_app(Settings(_env_file=None, llm_model=None, llm_api_key=None))
    ) as client:
        id = client.post("/api/v1/sessions").json()["session_id"]
        response = client.post(
            f"/api/v1/sessions/{id}/messages",
            json={"client_message_id": "m1", "content": "你好"},
        )
        assert response.status_code == 503
        assert client.get("/api/v1/sessions/missing").status_code == 404


def test_sse_uses_standard_events_and_prevalidates_unknown_runs(monkeypatch, fake_model_factory):
    import json

    async def handler(schema, messages):
        return {"intent": "general_chat", "action": "answer"} if schema else "你好\n第二行"

    monkeypatch.setattr("app.main.create_llm_service", lambda _: fake_model_factory(handler))
    with TestClient(create_app(settings())) as client:
        assert client.get("/api/v1/sessions/missing/runs/missing/events").status_code == 404
        id = client.post("/api/v1/sessions").json()["session_id"]
        assert client.get(f"/api/v1/sessions/{id}/runs/missing/events").status_code == 404
        run = client.post(
            f"/api/v1/sessions/{id}/messages",
            json={"client_message_id": "sse", "content": "你好"},
        ).json()
        with client.stream(
            "GET", f"/api/v1/sessions/{id}/runs/{run['run_id']}/events"
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["x-accel-buffering"] == "no"
            assert response.headers["cache-control"] == "no-cache"
            lines = list(response.iter_lines())
        assert "retry: 3000" in lines
        assert "event: snapshot" in lines and "event: done" in lines
        payloads = [json.loads(line[6:]) for line in lines if line.startswith("data: ")]
        assert payloads[-1]["run"]["message"]["content"] == "你好\n第二行"


@pytest.mark.parametrize("ending", ["done", "disconnect"])
def test_sse_idle_ping_keeps_iterator_alive_and_closes_on_end_or_disconnect(monkeypatch, ending):
    # 缩短框架的测试时钟；业务流等待实际收到 ping 后才结束，不靠固定 sleep。
    monkeypatch.setattr("fastapi.routing._PING_INTERVAL", 0.01)

    async def scenario():
        ping_received = asyncio.Event()
        disconnected = asyncio.Event()
        closed = False
        run = RunView(run_id="run", client_message_id="m1", status="running", stage="正在回答")

        async def events():
            nonlocal closed
            try:
                yield RunEvent(event="snapshot", run=run)
                await ping_received.wait()
                if ending == "disconnect":
                    await asyncio.Event().wait()
                yield RunEvent(event="done", run=run.model_copy(update={"status": "succeeded"}))
            finally:
                closed = True

        app = create_app(Settings(_env_file=None, llm_model=None, llm_api_key=None))
        async def prepare_events(*args):
            return events()
        app.state.conversation_service = SimpleNamespace(stream_run=prepare_events)
        bodies = []

        async def send(message):
            if message["type"] == "http.response.body":
                body = message.get("body", b"")
                bodies.append(body)
                if b": ping\n\n" in body:
                    ping_received.set()
                    if ending == "disconnect":
                        disconnected.set()

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        await asyncio.wait_for(
            app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.0"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": "/api/v1/sessions/session/runs/run/events",
                    "query_string": b"",
                    "headers": [],
                    "server": ("test", 80),
                    "client": ("test", 1234),
                },
                receive,
                send,
            ),
            timeout=1,
        )
        assert ping_received.is_set() and closed
        if ending == "done":
            assert b"event: done\n" in b"".join(bodies)

    asyncio.run(scenario())


def test_upload_and_input_boundaries(docx_bytes_factory):
    with TestClient(
        create_app(Settings(_env_file=None, llm_model=None, llm_api_key=None))
    ) as client:
        id = client.post("/api/v1/sessions").json()["session_id"]
        response = client.post(
            f"/api/v1/sessions/{id}/files",
            files={"file": ("草稿.docx", docx_bytes_factory())},
        )
        assert response.status_code == 201
        assert (
            response.json()["original_name"] == "草稿.docx" and response.json()["content_chars"] > 0
        )
        assert client.get(f"/api/v1/sessions/{id}").json()["messages"] == []
        assert (
            client.post(
                f"/api/v1/sessions/{id}/files", files={"file": ("x.doc", b"bad")}
            ).status_code
            == 415
        )
        assert (
            client.post(f"/api/v1/sessions/{id}/messages", json={"content": " "}).status_code
            == 422
        )


def test_message_accepts_no_documents():
    assert MessageCreate(client_message_id="m1", content="你好").file_ids == []


@pytest.mark.parametrize("updates", [{"content": "  "}, {"extra": True}, {"content": "x" * 12001}])
def test_invalid_message_is_rejected(updates):
    with pytest.raises(ValidationError):
        MessageCreate.model_validate({"client_message_id": "m1", "content": "你好"} | updates)


@pytest.mark.parametrize(
    "filename,content,code",
    [
        ("x.doc", b"x", "UNSUPPORTED_DOCUMENT_TYPE"),
        ("x.docx", b"broken", "INVALID_DOCX"),
        ("x.docx", b"", "EMPTY_DOCUMENT"),
    ],
)
def test_invalid_uploaded_document_rejected(filename, content, code):
    with TestClient(
        create_app(Settings(_env_file=None, llm_model=None, llm_api_key=None))
    ) as client:
        id = client.post("/api/v1/sessions").json()["session_id"]
        response = client.post(
            f"/api/v1/sessions/{id}/files", files={"file": (filename, content)}
        )
        assert response.status_code in {415, 422}
        assert response.json()["error"]["code"] == code
