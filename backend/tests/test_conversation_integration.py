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
        f"/api/v1/sessions/{id}/messages",
        json={
            "client_message_id": str(index),
            "content": text,
            "file_ids": documents or [],
        },
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    for _ in range(100):
        run = client.get(f"/api/v1/sessions/{id}/runs/{run_id}").json()
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

    async def traced_invoke(runtime, agent_id, payload, *, on_event=None, resources=None):
        calls.append((runtime, agent_id))
        return await original_invoke(
            runtime, agent_id, payload, on_event=on_event, resources=resources
        )

    def counted_build(*args, **kwargs):
        builds.append(1)
        return original_build(*args, **kwargs)

    monkeypatch.setattr(AgentRuntime, "invoke", traced_invoke)
    monkeypatch.setattr(review_package, "build_review_graph", counted_build)
    model = install_model(monkeypatch, fake_model_factory, ["chat", "documents", "documents"])
    with TestClient(app()) as client:
        id = client.post("/api/v1/sessions").json()["session_id"]
        assert send(client, id, "你好", 1)["message"]["agent_call"] is None
        ids = []
        for filename in ("draft.docx", "standard.docx"):
            response = client.post(
                f"/api/v1/sessions/{id}/files",
                files={
                    "file": (filename, docx_bytes_factory(title=filename, body="第一条 适用范围")),
                },
            )
            assert response.status_code == 201
            ids.append(response.json()["file_id"])
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
        id = client.post("/api/v1/sessions").json()["session_id"]
        send(client, id, "请审核制度", 1)
        result = send(client, id, "先不审核了，聊点别的", 2)
        assert result["message"]["agent_call"] is None
        assert all(
            schema is None or schema.__name__ == "IntentDecision" for schema, _ in model.calls
        )
        async def pending():
            from app.schemas.conversation_turn import conversation_thread_id

            saver = client.app.state.conversation_service._checkpoints.saver
            checkpoint = await saver.aget_tuple({
                "configurable": {"thread_id": conversation_thread_id("conversation_assistant", id)}
            })
            return checkpoint.checkpoint["channel_values"]["pending_review"]

        assert client.portal.call(pending) is None


def test_plain_text_review_without_file_upload(monkeypatch, fake_model_factory):
    install_model(monkeypatch, fake_model_factory, ["chat", "chat", "text"])
    with TestClient(app()) as client:
        id = client.post("/api/v1/sessions").json()["session_id"]
        send(client, id, "第一条 草稿须履行复核程序", 1)
        send(client, id, "第一条 标准要求双人复核", 2)
        result = send(client, id, "以上分别为草稿和标准，请进行制度审核", 3)
        assert "一. 简述" in result["message"]["agent_call"]["output"]
        assert client.get(f"/api/v1/sessions/{id}").json()["files"] == []


def test_summary_then_review_uses_original_and_restart_ignores_uncommitted_branch(
    actor, monkeypatch, fake_model_factory,
):
    import json
    from uuid import uuid4

    from app.schemas.conversation_session import SessionSubmission
    from app.schemas.conversation_turn import ConversationTurnResources, conversation_thread_id

    references, contexts, review_prompts, child_inputs = {}, [], [], []
    original_invoke = AgentRuntime.invoke

    async def traced_invoke(runtime, agent_id, payload, *, on_event=None, resources=None):
        if agent_id == "institution_review":
            child_inputs.append(payload)
        return await original_invoke(
            runtime, agent_id, payload, on_event=on_event, resources=resources,
        )

    monkeypatch.setattr(AgentRuntime, "invoke", traced_invoke)
    draft = "第一条  草稿须履行复核程序。\n第二条  保留完整空白。"
    standard = "第一条 标准要求双人复核。"

    async def handler(schema, messages):
        if schema and schema.__name__ == "SummaryOutput":
            return {"text": "已讨论草稿和审核标准，原文通过材料 ID 保留。"}
        if schema and schema.__name__ == "IntentDecision":
            context = json.loads(messages[-1][1])
            contexts.append(context)
            if context["messages"][-1]["content"] == "审核最早原文":
                return {
                    "intent": "institution_review", "action": "call_agent",
                    "target_agent_id": "institution_review", "review_args": {
                        "draft": {"kind": "user_message", "id": references["draft"]},
                        "standard": {"kind": "user_message", "id": references["standard"]},
                        "review_mode": "standard_document",
                    },
                }
            return {"intent": "general_chat", "action": "answer"}
        if schema and schema.__name__ == "StandardReviewOutput":
            review_prompts.append(messages[-1][1])
        return schema() if schema else "受控回答"

    monkeypatch.setattr("app.main.create_llm_service", lambda _: fake_model_factory(handler))
    with TestClient(app()) as client:
        sid = client.post("/api/v1/sessions").json()["session_id"]
        send(client, sid, draft, 1)
        send(client, sid, standard, 2)
        archived = client.get(f"/api/v1/sessions/{sid}").json()["messages"]
        references.update(draft=archived[0]["message_id"], standard=archived[2]["message_id"])
        for index in range(3, 8):
            send(client, sid, f"继续讨论 {index}", index)
        assert contexts[-1]["summary"]
        assert references["draft"] not in [m["id"] for m in contexts[-1]["messages"]]
        result = send(client, sid, "审核最早原文", 8)
        assert result["message"]["agent_call"]
        assert child_inputs[0]["content"] == draft
        assert child_inputs[0]["standard_content"] == standard
        reviews_before_restart = len(review_prompts)

        async def execute_without_business_commit():
            service = client.app.state.conversation_service
            submitted = await service._store.submit(
                actor, sid, SessionSubmission("interrupted", "不应保留的未提交消息"),
            )
            turn = await service._store.load_turn(
                actor, sid, submitted.run.run_id, assistant_message_id=str(uuid4()),
            )
            result = await service.runtime.invoke(
                turn.agent_id,
                turn.model_dump(),
                resources=ConversationTurnResources(
                    service._material_reader(actor.user.user_id, sid)
                ),
            )
            assert result.output.checkpoint_id != turn.checkpoint_id
            return submitted.run.run_id

        interrupted = client.portal.call(execute_without_business_commit)
    with TestClient(app()) as client:
        restored = client.get(f"/api/v1/sessions/{sid}/runs/{interrupted}").json()
        assert restored["error"]["code"] == "CONVERSATION_INTERRUPTED"
        send(client, sid, "重启后继续", 9)
        assert "不应保留的未提交消息" not in json.dumps(contexts[-1], ensure_ascii=False)
        assert len(review_prompts) == reviews_before_restart

        async def memory_state():
            service = client.app.state.conversation_service
            saved = await service._checkpoints.saver.aget_tuple({"configurable": {
                "thread_id": conversation_thread_id("conversation_assistant", sid),
            }})
            return saved.checkpoint["channel_values"]

        state = client.portal.call(memory_state)
        assert state["summary"]
        assert state["messages"][-1].content == "受控回答"


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
            id = client.post("/api/v1/sessions").json()["session_id"]
            ids = []
            for filename in ("draft.docx", "standard.docx"):
                body = "\n".join(f"第{i}条 {key}原文" for i in range(1, 5))
                response = client.post(
                    f"/api/v1/sessions/{id}/files",
                    files={"file": (filename, docx_bytes_factory(title=filename, body=body))},
                )
                assert response.status_code == 201
                ids.append(response.json()["file_id"])
            sessions[key] = (id, ids)

        def submit(key):
            id, ids = sessions[key]
            response = client.post(
                f"/api/v1/sessions/{id}/messages",
                json={"client_message_id": key, "content": "按标准审核", "file_ids": ids},
            )
            assert response.status_code == 202
            return response.json()["run_id"]

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
        response = client.post(f"/api/v1/sessions/{id}/runs/{first_id}/cancel")
        assert response.status_code == 202
        assert response.json()["status"] == "cancelled"
        assert client.portal.call(lambda: active["FIRST"]) == 0
        messages = client.get(f"/api/v1/sessions/{id}").json()["messages"]
        assert all(not m.get("agent_call") for m in messages)

        client.portal.call(wait_entered, "OTHER")
        client.portal.call(release_and_wait, "OTHER", other_id)
        other_session = sessions["OTHER"][0]
        assert (
            client.get(f"/api/v1/sessions/{other_session}/runs/{other_id}").json()["status"]
            == "succeeded"
        )
        next_id = submit("NEXT")
        client.portal.call(wait_entered, "NEXT")
        assert client.portal.call(lambda: active["NEXT"]) == 3
        client.portal.call(release_and_wait, "NEXT", next_id)
        assert client.portal.call(lambda: dict(peaks)) == {"FIRST": 3, "OTHER": 3, "NEXT": 3}
        assert client.portal.call(lambda: dict(active)) == {"FIRST": 0, "OTHER": 0, "NEXT": 0}


def test_cancel_after_graph_completion_keeps_committed_memory(monkeypatch, fake_model_factory):
    import asyncio

    model = install_model(monkeypatch, fake_model_factory, ["chat", "chat", "chat"])
    with TestClient(app()) as client:
        sid = client.post("/api/v1/sessions").json()["session_id"]
        send(client, sid, "成功轮", 1)
        service = client.app.state.conversation_service
        original_finish = service._finish
        block = {"enabled": True}

        async def setup():
            return asyncio.Event()

        entered = client.portal.call(setup)

        async def before_commit(owner, session_id, run_id, completion):
            if completion.status == "succeeded" and block["enabled"]:
                entered.set()
                await asyncio.Event().wait()
            return await original_finish(owner, session_id, run_id, completion)

        monkeypatch.setattr(service, "_finish", before_commit)
        submitted = client.post(
            f"/api/v1/sessions/{sid}/messages",
            json={"client_message_id": "2", "content": "图完成但未提交"},
        ).json()
        client.portal.call(asyncio.wait_for, entered.wait(), 5)
        cancelled = client.post(f"/api/v1/sessions/{sid}/runs/{submitted['run_id']}/cancel")
        assert cancelled.json()["status"] == "cancelled"
        block["enabled"] = False
        send(client, sid, "取消后继续", 3)
        contexts = [
            json.loads(messages[-1][1])
            for schema, messages in model.calls
            if schema and schema.__name__ == "IntentDecision"
        ]
        contents = [message["content"] for message in contexts[-1]["messages"]]
        assert "成功轮" in contents
        assert "图完成但未提交" not in contents
