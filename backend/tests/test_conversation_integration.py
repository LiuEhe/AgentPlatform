"""真实注册表、会话服务和制度审核图的跨层测试，外部模型受控替代。"""

import json

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.runtime.agent_runtime import AgentRuntime


def install_model(monkeypatch, fake_model_factory, routes):
    async def handler(schema, messages):
        if schema and schema.__name__ == "IntentDecision":
            context = json.loads(messages[-1][1])
            route = routes.pop(0)
            if route == "clarify":
                return {
                    "intent": "institution_review",
                    "action": "clarify",
                    "question": "请提供草稿和审核方式",
                    "pending_action": "update",
                }
            if route == "chat":
                return {"intent": "general_chat", "action": "answer"}
            if route == "documents":
                refs = {
                    doc["filename"]: {"kind": "document", "id": doc["id"]}
                    for doc in context["documents"]
                }
                draft, standard = refs["draft.docx"], refs["standard.docx"]
            else:
                users = [m for m in context["messages"] if m["role"] == "user"]
                draft = {"kind": "user_message", "id": users[0]["id"]}
                standard = {"kind": "user_message", "id": users[1]["id"]}
            return {
                "intent": "institution_review",
                "action": "call_agent",
                "target_agent_id": "institution_review",
                "review_args": {
                    "draft": draft,
                    "standard": standard,
                    "review_mode": "standard_document",
                },
            }
        return schema() if schema else "受控模型回答，不涉及外部服务。"

    model = fake_model_factory(handler)
    monkeypatch.setattr("app.main.create_llm_service", lambda _: model)
    return model


def app():
    return create_app(
        Settings(
            _env_file=None,
            llm_model="test",
            llm_api_key="test",
            ragflow_base_url=None,
            ragflow_api_key=None,
            ragflow_dataset_id=None,
        )
    )


def send(client, id, text, index, documents=None):
    response = client.post(
        f"/api/v1/conversations/{id}/messages",
        json={
            "client_message_id": str(index),
            "content": text,
            "document_ids": documents or [],
        },
    )
    assert response.status_code == 202
    run_id = response.json()["id"]
    for _ in range(100):
        run = client.get(f"/api/v1/conversations/{id}/runs/{run_id}").json()
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            break
    assert run["status"] == "succeeded", run
    return run


def test_chat_then_standard_review_through_registered_agents(
    monkeypatch,
    fake_model_factory,
    docx_bytes_factory,
):
    import app.agents.institution_review as review_package

    calls, builds = [], []
    original_invoke = AgentRuntime.invoke
    original_build = review_package.build_review_graph

    async def traced_invoke(runtime, agent_id, payload, *, on_event=None):
        calls.append((runtime, agent_id))
        return await original_invoke(runtime, agent_id, payload, on_event=on_event)

    def counted_build(*args, **kwargs):
        builds.append(1)
        return original_build(*args, **kwargs)

    monkeypatch.setattr(AgentRuntime, "invoke", traced_invoke)
    monkeypatch.setattr(review_package, "build_review_graph", counted_build)
    model = install_model(monkeypatch, fake_model_factory, ["chat", "documents", "documents"])
    with TestClient(app()) as client:
        id = client.post("/api/v1/conversations").json()["id"]
        assert send(client, id, "你好", 1)["message"]["agent_call"] is None
        ids = []
        for filename in ("draft.docx", "standard.docx"):
            response = client.post(
                f"/api/v1/conversations/{id}/documents",
                files={
                    "file": (filename, docx_bytes_factory(title=filename, body="第一条 适用范围")),
                },
            )
            assert response.status_code == 201
            ids.append(response.json()["id"])
        result = send(client, id, "按标准审核草稿", 2, ids)
        call = result["message"]["agent_call"]
        assert call["agent_id"] == "institution_review"
        assert call["invocation_id"]
        assert "一. 简述" in call["output"]
        assert any(
            schema and schema.__name__ == "StandardReviewOutput" for schema, _ in model.calls
        )
        assert send(client, id, "再按标准审核", 3, ids)["message"]["agent_call"]
        assert len({runtime for runtime, _ in calls}) == 1
        assert [agent for _, agent in calls].count("institution_review") == 2
        assert builds == [1]


def test_pending_review_then_smalltalk_never_executes_review(monkeypatch, fake_model_factory):
    model = install_model(monkeypatch, fake_model_factory, ["clarify", "chat"])
    with TestClient(app()) as client:
        id = client.post("/api/v1/conversations").json()["id"]
        send(client, id, "请审核制度", 1)
        result = send(client, id, "先不审核了，聊点别的", 2)
        assert result["message"]["agent_call"] is None
        assert all(
            schema is None or schema.__name__ == "IntentDecision" for schema, _ in model.calls
        )
        assert client.app.state.conversation_service._store.record(id).continuation is None


def test_plain_text_review_without_file_upload(monkeypatch, fake_model_factory):
    install_model(monkeypatch, fake_model_factory, ["chat", "chat", "text"])
    with TestClient(app()) as client:
        id = client.post("/api/v1/conversations").json()["id"]
        send(client, id, "第一条 草稿须履行复核程序", 1)
        send(client, id, "第一条 标准要求双人复核", 2)
        result = send(client, id, "以上分别为草稿和标准，请进行制度审核", 3)
        assert "一. 简述" in result["message"]["agent_call"]["output"]
        assert client.get(f"/api/v1/conversations/{id}").json()["documents"] == []


def test_cancel_conversation_waits_for_review_chunk_cleanup(
    monkeypatch,
    fake_model_factory,
    docx_bytes_factory,
):
    import asyncio

    model = install_model(monkeypatch, fake_model_factory, ["documents"] * 3)
    original_handler = model.handler
    controls = None
    active = {key: 0 for key in ("FIRST", "OTHER", "NEXT")}
    peaks = dict(active)

    async def handler(schema, messages):
        prompt = messages[-1][1]
        if schema and schema.__name__ == "StandardReviewOutput":
            key = next(key for key in active if key in prompt)
            active[key] += 1
            peaks[key] = max(peaks[key], active[key])
            controls["entered"][key].put_nowait(key)
            try:
                await controls[key].wait()
            finally:
                active[key] -= 1
            return schema()
        if schema is None and "检查全文" in prompt and "OTHER" in prompt:
            controls["other_terminology"].set()
        return await original_handler(schema, messages)

    model.handler = handler
    with TestClient(app()) as client:

        async def make_controls():
            return {
                "entered": {key: asyncio.Queue() for key in active},
                "other_terminology": asyncio.Event(),
                **{key: asyncio.Event() for key in active},
            }

        controls = client.portal.call(make_controls)
        sessions = {}
        for key in active:
            id = client.post("/api/v1/conversations").json()["id"]
            ids = []
            for filename in ("draft.docx", "standard.docx"):
                body = "\n".join(f"第{i}条 {key}原文" for i in range(1, 5))
                response = client.post(
                    f"/api/v1/conversations/{id}/documents",
                    files={"file": (filename, docx_bytes_factory(title=filename, body=body))},
                )
                assert response.status_code == 201
                ids.append(response.json()["id"])
            sessions[key] = (id, ids)

        def submit(key):
            id, ids = sessions[key]
            response = client.post(
                f"/api/v1/conversations/{id}/messages",
                json={"client_message_id": key, "content": "按标准审核", "document_ids": ids},
            )
            assert response.status_code == 202
            return response.json()["id"]

        async def wait_entered(key):
            async with asyncio.timeout(5):
                for _ in range(3):
                    assert await controls["entered"][key].get() == key

        async def release_and_wait(key, run_id):
            task = client.app.state.conversation_service._tasks.get(run_id)
            controls[key].set()
            if task:
                await asyncio.wait_for(task, 5)

        first_id = submit("FIRST")
        client.portal.call(wait_entered, "FIRST")
        other_id = submit("OTHER")
        client.portal.call(asyncio.wait_for, controls["other_terminology"].wait(), 5)
        id = sessions["FIRST"][0]
        response = client.post(f"/api/v1/conversations/{id}/runs/{first_id}/cancel")
        assert response.status_code == 202
        assert response.json()["status"] == "cancelled"
        assert client.portal.call(lambda: active["FIRST"]) == 0
        messages = client.get(f"/api/v1/conversations/{id}").json()["messages"]
        assert all(not m.get("agent_call") for m in messages)

        client.portal.call(wait_entered, "OTHER")
        client.portal.call(release_and_wait, "OTHER", other_id)
        other_session = sessions["OTHER"][0]
        assert (
            client.get(f"/api/v1/conversations/{other_session}/runs/{other_id}").json()["status"]
            == "succeeded"
        )
        next_id = submit("NEXT")
        client.portal.call(wait_entered, "NEXT")
        assert client.portal.call(lambda: active["NEXT"]) == 3
        client.portal.call(release_and_wait, "NEXT", next_id)
        assert client.portal.call(lambda: dict(peaks)) == {"FIRST": 3, "OTHER": 3, "NEXT": 3}
        assert client.portal.call(lambda: dict(active)) == {"FIRST": 0, "OTHER": 0, "NEXT": 0}
