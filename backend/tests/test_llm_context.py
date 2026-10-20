import json

import pytest

from app.nodes.llm.context import ContextBudgetError, ContextItem, build_context


def test_required_content_is_never_silently_dropped():
    with pytest.raises(ContextBudgetError):
        build_context(
            {},
            required_items=[ContextItem("messages", {"content": '"\\\n' * 4000}, 0)],
            optional_items=[],
            max_chars=24000,
            omission_note="省略",
        )


def test_budget_counts_serialized_excerpts_and_metadata():
    result = build_context(
        {"metadata": "x" * 50},
        required_items=[ContextItem("messages", {"content": "你好"}, 1)],
        optional_items=[ContextItem("documents", {"content": "\\" * 40000}, 0, "content")],
        max_chars=24000,
        omission_note="省略",
    )
    assert len(json.dumps(result.payload, ensure_ascii=False, separators=(",", ":"))) <= 24000
    assert result.payload["messages"][0]["content"] == "你好"
    assert result.omitted and result.payload["coverage_note"] == "省略"


def test_context_retains_original_order_and_reports_prior_clipping():
    result = build_context(
        {},
        required_items=[ContextItem("messages", {"content": "new"}, 2)],
        optional_items=[
            ContextItem("messages", {"content": "middle"}, 1, already_truncated=True),
            ContextItem("messages", {"content": "old"}, 0),
        ],
        max_chars=24000,
        omission_note="部分内容",
    )
    assert [m["content"] for m in result.payload["messages"]] == ["old", "middle", "new"]
    assert result.omitted
