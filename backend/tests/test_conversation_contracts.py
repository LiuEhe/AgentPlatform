import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.conversation_turn import (
    ChildAgentResult,
    ContinuationState,
    ConversationTurnInput,
    ConversationTurnResult,
    TurnMessage,
)


def test_turn_input_accepts_no_documents():
    turn = ConversationTurnInput(
        latest_message_id="m1", messages=(TurnMessage(id="m1", role="user", content="你好"),)
    )
    assert turn.documents == () and turn.continuation is None


def test_turn_result_is_executed_output():
    result = ConversationTurnResult(reply="你好")
    assert result.child_call is None
    assert "intent" not in ConversationTurnResult.model_fields
    for reply in (" ", "x" * 200001):
        with pytest.raises(ValidationError):
            ConversationTurnResult(reply=reply)
    with pytest.raises(ValidationError):
        ChildAgentResult(
            id="c",
            agent_id="a",
            agent_name="助手",
            invocation_id="i",
            output_type="markdown",
            output=" ",
        )


def test_continuation_payload_is_opaque():
    continuation = ContinuationState(payload={"unrelated": {"value": 1}})
    assert continuation.payload == {"unrelated": {"value": 1}}
    assert continuation.question_message_id is None


def test_internal_contracts_do_not_import_http_views():
    root = Path(__file__).parents[1] / "app" / "schemas"
    for filename in ("conversation_turn.py", "conversation_session.py"):
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert "app.schemas.conversation" not in modules
        assert not any(module.startswith("app.services") for module in modules)
