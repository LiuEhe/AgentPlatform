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

    async def traced_invoke(runtime, agent_id, payload):
        calls.append((runtime, agent_id))
        return await original_invoke(runtime, agent_id, payload)

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
