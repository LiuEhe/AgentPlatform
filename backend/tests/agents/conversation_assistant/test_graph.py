import asyncio
import json

import pytest

from app.agents.conversation_assistant.config import ConversationAgentConfig
from app.agents.conversation_assistant.graph.graph import build_conversation_graph
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentExecution
from app.schemas.conversation_turn import TurnDocument

CONFIG = ConversationAgentConfig(True, 50000)


@pytest.mark.parametrize(
    "intent,text",
    [
        ("general_chat", "你好"),
        ("institution_qa", "制度审核关注什么"),
        ("general_chat", "写请假邮件"),
        ("general_chat", "总结这份文档"),
    ],
)
def test_plain_branches_never_invoke_child(fake_model_factory, turn_factory, intent, text):
    async def handler(schema, messages):
        return {"intent": intent, "action": "answer"} if schema else "直接回答"

    async def child(*args):
        pytest.fail("普通对话不应调用子智能体")

    graph = build_conversation_graph(fake_model_factory(handler), child, config=CONFIG)
    state = asyncio.run(graph.ainvoke({"turn": turn_factory(content=text)}))
    assert state["result"].reply == "直接回答" and state["result"].child_call is None


def test_review_missing_parameters_clarifies(fake_model_factory, turn_factory):
    async def handler(schema, messages):
        assert schema is not None
        return {
            "intent": "institution_review",
            "action": "call_agent",
            "target_agent_id": "institution_review",
        }

    async def child(*args):
        pytest.fail("缺参不能执行")

    state = asyncio.run(
        build_conversation_graph(
            fake_model_factory(handler),
            child,
            config=CONFIG,
        ).ainvoke({"turn": turn_factory()})
    )
    assert "草稿" in state["result"].reply and state["result"].continuation


def test_review_calls_once_with_full_text_and_no_rewrite(fake_model_factory, turn_factory):
    calls = []
    original = "# 草稿\n第一条  原文" + "\\" * 30000

    async def handler(schema, messages):
        assert schema is not None
        return {
            "intent": "institution_review",
            "action": "call_agent",
            "target_agent_id": "institution_review",
            "review_args": {
                "draft": {"kind": "document", "id": "d"},
                "review_mode": "knowledge_base",
            },
        }

    async def child(agent_id, payload):
        calls.append((agent_id, payload))
        return AgentExecution("real-id", agent_id, "# 原始报告\n\n正文")

    model = fake_model_factory(handler)
    graph = build_conversation_graph(model, child, config=CONFIG)
    state = asyncio.run(
        graph.ainvoke(
            {
                "turn": turn_factory(
                    documents=(TurnDocument(id="d", filename="草稿.docx", markdown=original),)
                )
            }
        )
    )
    result = state["result"]
    assert result.child_call.output == "# 原始报告\n\n正文"
    assert result.child_call.invocation_id == "real-id"
    assert len(calls) == 1 and calls[0][1]["content"] == original
    assert len(model.calls) == 1 and result.continuation is None


def test_multiturn_topic_change_clears_pending(fake_model_factory, turn_factory):
    async def handler(schema, messages):
        if schema:
            latest = json.loads(messages[-1][1])["messages"][-1]["content"]
            return (
                {"intent": "institution_review", "action": "clarify", "question": "请提供草稿"}
                if latest == "审核"
                else {"intent": "general_chat", "action": "answer"}
            )
        return "聊点别的"

    async def child(*args):
        pytest.fail("不应调用")

    async def scenario():
        graph = build_conversation_graph(fake_model_factory(handler), child, config=CONFIG)
        first = await graph.ainvoke({"turn": turn_factory(content="审核")})
        assert first["result"].continuation
        second = await graph.ainvoke(
            {
                "turn": turn_factory(
                    content="先不审核",
                    continuation=first["result"].continuation,
                )
            }
        )
        assert second["result"].continuation is None

    asyncio.run(scenario())


def test_one_compiled_graph_isolates_concurrent_turns(fake_model_factory, turn_factory):
    async def handler(schema, messages):
        if schema:
            return {"intent": "general_chat", "action": "answer"}
        return json.loads(messages[-1][1])["messages"][-1]["content"]

    async def child(*args):
        pytest.fail("不应调用")

    async def scenario():
        graph = build_conversation_graph(fake_model_factory(handler), child, config=CONFIG)
        a, b = await asyncio.gather(
            *[graph.ainvoke({"turn": turn_factory(content=text)}) for text in ("甲", "乙")]
        )
        assert (a["result"].reply, b["result"].reply) == ("甲", "乙")

    asyncio.run(scenario())


@pytest.mark.parametrize("switch_mode", [False, True])
def test_followup_completes_pending_review_once(fake_model_factory, turn_factory, switch_mode):
    draft = {"kind": "document", "id": "d"}
    standard = {"kind": "document", "id": "s"}
    decisions = [
        {
            "intent": "institution_review",
            "action": "clarify",
            "question": "请补齐材料",
            "pending_action": "update",
            "review_args": {
                "review_mode": "standard_document",
                **({"standard": standard} if switch_mode else {"draft": draft}),
            },
        },
        {
            "intent": "institution_review",
            "action": "call_agent",
            "target_agent_id": "institution_review",
            "pending_action": "keep",
            "review_args": (
                {"draft": draft, "review_mode": "knowledge_base", "standard": None}
                if switch_mode
                else {"standard": standard}
            ),
        },
    ]

    async def handler(schema, messages):
        assert schema is not None
        return decisions.pop(0)

    calls = []

    async def child(agent_id, payload):
        calls.append(payload)
        return AgentExecution("i", agent_id, "# 审核结果")

    async def scenario():
        graph = build_conversation_graph(fake_model_factory(handler), child, config=CONFIG)
        turn = turn_factory(
            documents=(
                TurnDocument(id="d", filename="草稿.docx", markdown="# 草稿\n第一条 草稿"),
                TurnDocument(id="s", filename="标准.docx", markdown="# 标准\n第一条 标准"),
            )
        )
        first = await graph.ainvoke({"turn": turn})
        assert first["result"].continuation and calls == []
        turn = turn.model_copy(update={"continuation": first["result"].continuation})
        second = await graph.ainvoke({"turn": turn})
        assert second["result"].child_call and second["result"].continuation is None
        assert len(calls) == 1 and calls[0]["content"] == turn.documents[0].markdown
        if switch_mode:
            assert calls[0]["review_mode"] == "knowledge_base"
            assert "standard_content" not in calls[0]
        else:
            assert calls[0]["standard_content"] == turn.documents[1].markdown

    asyncio.run(scenario())


def test_invalid_model_output_cannot_invoke_child(fake_model_factory, turn_factory):
    async def handler(schema, messages):
        return {"intent": "general_chat", "action": "call_agent", "target_agent_id": "unknown"}

    async def child(*args):
        pytest.fail("非法输出不能调用")

    with pytest.raises(AppError):
        asyncio.run(
            build_conversation_graph(
                fake_model_factory(handler),
                child,
                config=CONFIG,
            ).ainvoke({"turn": turn_factory()})
        )


@pytest.mark.parametrize("cancel", [False, True])
def test_child_failure_and_cancellation_propagate(fake_model_factory, turn_factory, cancel):
    async def handler(schema, messages):
        return {
            "intent": "institution_review",
            "action": "call_agent",
            "target_agent_id": "institution_review",
            "review_args": {
                "draft": {"kind": "user_message", "id": "m1"},
                "review_mode": "knowledge_base",
            },
        }

    async def scenario():
        entered = asyncio.Event()

        async def child(*args):
            entered.set()
            if cancel:
                await asyncio.Event().wait()
            raise AppError("CHILD_FAILED", "审核失败", 502)

        graph = build_conversation_graph(fake_model_factory(handler), child, config=CONFIG)
        task = asyncio.create_task(graph.ainvoke({"turn": turn_factory()}))
        if cancel:
            await entered.wait()
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else AppError):
            await task

    asyncio.run(scenario())
