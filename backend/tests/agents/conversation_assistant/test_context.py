import pytest

from app.agents.conversation_assistant.nodes.context_prepare import prepare_context
from app.core.errors import AppError
from app.schemas.conversation_turn import ChildAgentResult, TurnDocument, TurnMessage


def test_empty_document_selection_builds_chat_context(turn_factory):
    context = prepare_context(turn_factory(), [])
    assert context.documents == [] and context.messages[0]["content"] == "你好"


def test_document_excerpt_fits_serialized_budget(turn_factory):
    document = TurnDocument(id="d1", filename="长文.docx", markdown="\\" * 40000)
    turn = turn_factory(documents=(document,))
    context = prepare_context(turn, [])
    assert len(context.model_dump_json()) <= 24000 and context.coverage_note
    assert turn.documents[0].markdown == document.markdown


def test_current_message_is_never_dropped_for_json_escaping(turn_factory):
    with pytest.raises(AppError) as raised:
        prepare_context(turn_factory(content='"\\\n' * 4000), [])
    assert raised.value.code == "CONVERSATION_INPUT_TOO_LONG"


def test_history_result_excerpt_is_bounded(turn_factory):
    history = (
        TurnMessage(
            id="old",
            role="assistant",
            content="审核结果",
            agent_call=ChildAgentResult(
                id="c",
                agent_id="a",
                agent_name="助手",
                invocation_id="i",
                output_type="markdown",
                output="正文" * 10000,
            ),
        ),
    )
    context = prepare_context(turn_factory(history=history), [])
    assert len(context.messages[0]["agent_result"]) == 4000
    assert context.coverage_note
