"""真实编译图的增量记忆、失败分支、摘要和原文引用。"""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.errors import AppError
from app.schemas.conversation_turn import (
    ConversationTurnInput,
    ConversationTurnResources,
    MaterialReference,
    TurnMaterial,
    TurnMessage,
    conversation_thread_id,
)


def make_turn(
    *,
    session_id=None,
    checkpoint_id=None,
    sequence=1,
    content="你好",
    agent_id="conversation_assistant",
):
    return ConversationTurnInput(
        agent_id=agent_id, session_id=session_id or str(uuid4()), run_id=str(uuid4()),
        checkpoint_id=checkpoint_id,
        message=TurnMessage(id=str(uuid4()), sequence=sequence, role="user", content=content),
        assistant_message_id=str(uuid4()), assistant_sequence=sequence + 1,
    )


class Model:
    def __init__(self):
        self.inputs = []
        self.fail = False
        self.decision = {"intent": "general_chat", "action": "answer"}

    def with_structured_output(self, schema):
        async def invoke(messages):
            if schema.__name__ == "SummaryOutput":
                return {"text": "用户明确要求保留之前的决定。"}
            self.inputs.append(json.loads(messages[-1][1]))
            return self.decision
        return SimpleNamespace(ainvoke=invoke)

    async def ainvoke(self, messages):
        if self.fail:
            raise RuntimeError("controlled failure")
        return "收到"


async def call(adapter, turn, *, reader=None):
    async def missing(refs):
        raise AppError("MATERIAL_NOT_FOUND", "会话材料不存在", 404)
    return await adapter.invoke(turn.model_dump(), SimpleNamespace(
        agent_id=turn.agent_id, invocation_id=str(uuid4()), on_event=None,
        resources=ConversationTurnResources(reader or missing),
    ))


def build(model, child=None):
    from app.agents.conversation_assistant.adapter import ConversationAssistantAgent
    from app.agents.conversation_assistant.config import ConversationAgentConfig
    from app.agents.conversation_assistant.graph.graph import build_conversation_graph

    async def forbidden(*args):
        pytest.fail("普通交流不能调用子审核")
    graph = build_conversation_graph(
        model, child or forbidden, config=ConversationAgentConfig(True, 50000),
        checkpointer=InMemorySaver(),
    )
    return ConversationAssistantAgent(graph), graph


def test_same_thread_receives_only_new_input():
    async def scenario():
        model = Model()
        adapter, graph = build(model)
        first = make_turn(content="我喜欢咖啡")
        result = await call(adapter, first)
        second = make_turn(session_id=first.session_id, checkpoint_id=result.checkpoint_id,
                           sequence=3, content="我喜欢什么？")
        result2 = await call(adapter, second)
        assert [m["content"] for m in model.inputs[-1]["messages"]] == [
            "我喜欢咖啡",
            "收到",
            "我喜欢什么？",
        ]
        state = await graph.aget_state({"configurable": {
            "thread_id": conversation_thread_id(second.agent_id, second.session_id),
            "checkpoint_id": result2.checkpoint_id,
        }})
        assert [m.id for m in state.values["messages"]] == [
            first.message.id,
            first.assistant_message_id,
            second.message.id,
            second.assistant_message_id,
        ]
        assert state.next == () and state.values["last_completed_run_id"] == second.run_id
    asyncio.run(scenario())


def test_two_threads_keep_messages_separate():
    async def scenario():
        model = Model()
        adapter, _ = build(model)
        await asyncio.gather(
            call(adapter, make_turn(content="甲")), call(adapter, make_turn(content="乙"))
        )
        assert sorted([p["messages"][-1]["content"] for p in model.inputs]) == ["乙", "甲"]
        assert all(len(p["messages"]) == 1 for p in model.inputs)
    asyncio.run(scenario())


def test_next_turn_uses_committed_checkpoint_not_latest():
    async def scenario():
        model = Model()
        adapter, _ = build(model)
        first = make_turn(content="已确认")
        accepted = await call(adapter, first)
        model.fail = True
        with pytest.raises(AppError):
            await call(
                adapter,
                make_turn(
                    session_id=first.session_id,
                    checkpoint_id=accepted.checkpoint_id,
                    sequence=3,
                    content="不应保留的半轮",
                ),
            )
        model.fail = False
        await call(
            adapter,
            make_turn(
                session_id=first.session_id,
                checkpoint_id=accepted.checkpoint_id,
                sequence=5,
                content="继续",
            ),
        )
        assert "不应保留的半轮" not in json.dumps(model.inputs[-1], ensure_ascii=False)
        assert "已确认" in json.dumps(model.inputs[-1], ensure_ascii=False)
    asyncio.run(scenario())


def test_summary_advances_only_over_completed_pairs():
    async def scenario():
        model = Model()
        adapter, graph = build(model)
        sid, checkpoint = str(uuid4()), None
        for index in range(7):
            turn = make_turn(session_id=sid, checkpoint_id=checkpoint,
                             sequence=2 * index + 1, content=f"事实 {index}")
            result = await call(adapter, turn)
            checkpoint = result.checkpoint_id
        state = await graph.aget_state({"configurable": {
            "thread_id": conversation_thread_id(turn.agent_id, sid), "checkpoint_id": checkpoint,
        }})
        assert state.values["summary"]
        assert state.values["summary_through_sequence"] >= 6
        assert state.values["messages"][-2].id == turn.message.id
        assert len(json.dumps(model.inputs[-1], ensure_ascii=False, separators=(",", ":"))) <= 24000
    asyncio.run(scenario())


def test_review_resolves_older_paste_by_id():
    async def scenario():
        model, calls = Model(), []
        original = "# 制度\n第一条  完整原文" + "依据" * 5000

        async def child(agent_id, payload):
            calls.append(payload)
            return SimpleNamespace(invocation_id="child", output="# 审核报告")

        adapter, _ = build(model, child)
        first = make_turn(content=original)
        accepted = await call(adapter, first)
        model.decision = {"intent": "institution_review", "action": "call_agent",
                          "target_agent_id": "institution_review", "review_args": {
                              "draft": {"kind": "user_message", "id": first.message.id},
                              "review_mode": "knowledge_base"}}

        async def reader(refs):
            assert refs == (MaterialReference(kind="user_message", id=first.message.id),)
            return (TurnMaterial(ref=refs[0], title="粘贴正文", content=original),)

        result = await call(
            adapter,
            make_turn(
                session_id=first.session_id,
                checkpoint_id=accepted.checkpoint_id,
                sequence=3,
                content="审核之前草稿",
            ),
            reader=reader,
        )
        assert calls[0]["content"] == original and result.child_call.output == "# 审核报告"
    asyncio.run(scenario())


def test_missing_committed_checkpoint_fails_before_model_call():
    async def scenario():
        model = Model()
        adapter, _ = build(model)
        with pytest.raises(AppError) as error:
            await call(adapter, make_turn(checkpoint_id="missing-checkpoint"))
        assert error.value.code == "STORAGE_UNAVAILABLE"
        assert model.inputs == []
    asyncio.run(scenario())


def test_summary_failure_can_retry_from_same_committed_position():
    class FailingSummary(Model):
        fail_summary = False

        def with_structured_output(self, schema):
            if schema.__name__ != "SummaryOutput" or not self.fail_summary:
                return super().with_structured_output(schema)

            async def fail(messages):
                raise ValueError("controlled summary failure")
            return SimpleNamespace(ainvoke=fail)

    async def scenario():
        model = FailingSummary()
        adapter, graph = build(model)
        sid, checkpoint = str(uuid4()), None
        for index in range(5):
            turn = make_turn(session_id=sid, checkpoint_id=checkpoint,
                             sequence=index * 2 + 1, content=f"事实{index}")
            checkpoint = (await call(adapter, turn)).checkpoint_id
        model.fail_summary = True
        failed = make_turn(session_id=sid, checkpoint_id=checkpoint, sequence=11, content="失败轮")
        with pytest.raises(AppError) as error:
            await call(adapter, failed)
        assert error.value.code == "MODEL_ERROR"
        parent = await graph.aget_state({"configurable": {
            "thread_id": conversation_thread_id(turn.agent_id, sid), "checkpoint_id": checkpoint,
        }})
        assert len(parent.values["messages"]) == 10
        model.fail_summary = False
        await call(adapter, make_turn(session_id=sid, checkpoint_id=checkpoint,
                                     sequence=13, content="重试"))
        assert "失败轮" not in json.dumps(model.inputs[-1], ensure_ascii=False)
        assert model.inputs[-1]["summary"]
    asyncio.run(scenario())


def test_summary_receives_review_excerpt_and_material_references():
    class CaptureSummary(Model):
        def __init__(self):
            super().__init__()
            self.summaries = []

        def with_structured_output(self, schema):
            if schema.__name__ != "SummaryOutput":
                return super().with_structured_output(schema)

            async def invoke(messages):
                self.summaries.append(json.loads(messages[-1][1]))
                return {"text": "已完成审核，发现关键风险"}
            return SimpleNamespace(ainvoke=invoke)

    async def scenario():
        model = CaptureSummary()

        async def child(agent_id, payload):
            return SimpleNamespace(invocation_id="child", output="关键风险" * 2000)

        adapter, _ = build(model, child)
        first = make_turn(content="第一条 草稿原文")
        accepted = await call(adapter, first)
        model.decision = {
            "intent": "institution_review", "action": "call_agent",
            "target_agent_id": "institution_review", "review_args": {
                "draft": {"kind": "user_message", "id": first.message.id},
                "review_mode": "knowledge_base",
            },
        }

        async def reader(refs):
            return (TurnMaterial(ref=refs[0], title="草稿", content=first.message.content),)

        result = await call(adapter, make_turn(
            session_id=first.session_id, checkpoint_id=accepted.checkpoint_id,
            sequence=3, content="审核之前草稿",
        ), reader=reader)
        assert len(result.child_call.output) == 8000
        model.decision = {"intent": "general_chat", "action": "answer"}
        for index in range(2, 7):
            turn = make_turn(session_id=first.session_id, checkpoint_id=result.checkpoint_id,
                             sequence=index * 2 + 1, content="继续讨论")
            result = await call(adapter, turn)
        serialized = json.dumps(model.summaries, ensure_ascii=False)
        assert "关键风险" in serialized
        assert "agent_result_truncated" in serialized
        assert "关键风险" * 2000 not in serialized
    asyncio.run(scenario())
