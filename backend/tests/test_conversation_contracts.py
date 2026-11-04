"""增量单轮与共享线程标识，不接受历史回灌和续接字段。"""

import ast
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.conversation_turn import ChildAgentResult, ConversationTurnInput, TurnMessage


def test_turn_accepts_only_one_new_message():
    from app.schemas.conversation_turn import conversation_thread_id

    sid = str(uuid4())
    data = dict(
        agent_id="conversation_assistant", session_id=sid, run_id=str(uuid4()),
        checkpoint_id=None, message=TurnMessage(id="m1", sequence=1, role="user", content="你好"),
        assistant_message_id="m2", assistant_sequence=2,
    )
    turn = ConversationTurnInput(**data)
    assert turn.material_catalog == ()
    assert conversation_thread_id(turn.agent_id, sid) == "conversation_assistant:" + sid
    for obsolete in ({"messages": []}, {"continuation": {}}, {"documents": []}):
        with pytest.raises(ValidationError):
            ConversationTurnInput(**data, **obsolete)


def test_thread_identity_is_shared_canonical_and_agent_scoped():
    from app.schemas.conversation_turn import conversation_thread_id

    sid = uuid4()
    assert conversation_thread_id("first", str(sid).upper()) == f"first:{sid}"
    assert conversation_thread_id("first", str(sid)) != conversation_thread_id("second", str(sid))
    for aid, value in (("bad:id", str(sid)), ("first", "not-a-uuid")):
        with pytest.raises(ValueError):
            conversation_thread_id(aid, value)


def test_turn_result_requires_real_checkpoint_and_stable_assistant_identity():
    from app.schemas.conversation_turn import ConversationTurnResult

    data = dict(
        reply="你好", checkpoint_id="checkpoint", assistant_message_id="m2", assistant_sequence=2
    )
    assert ConversationTurnResult(**data).child_call is None
    for update in ({"reply": " "}, {"reply": "x" * 200001}, {"checkpoint_id": ""}):
        with pytest.raises(ValidationError):
            ConversationTurnResult(**(data | update))
    with pytest.raises(ValidationError):
        ChildAgentResult(id="c", agent_id="a", agent_name="助手", invocation_id="i",
                         output_type="markdown", output=" ")


def test_internal_contracts_do_not_import_http_views():
    root = Path(__file__).parents[1] / "app" / "schemas"
    for filename in ("conversation_turn.py", "conversation_session.py"):
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert "app.schemas.conversation" not in modules
        assert not any(module.startswith("app.services") for module in modules)


def test_v4_has_checkpoint_pointer_without_continuation():
    sql = Path(__file__).parents[1] / "database" / "schema_v4.sql"
    assert sql.exists()
    text = sql.read_text(encoding="utf-8")
    assert "memory_checkpoint_id" in text and "continuation" not in text
    assert "CREATE TABLE checkpoints" not in text
