import asyncio

import pytest
from conftest import turn_resources
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.conversation_assistant.nodes.context_prepare import prepare_context
from app.agents.conversation_assistant.nodes.material_prepare import prepare_materials
from app.agents.conversation_assistant.schemas import ConversationExecutionContext
from app.core.errors import AppError
from app.schemas.conversation_turn import TurnDocument


def context_for(turn, documents=(), history=()):
    state = {
        "messages": [*history, HumanMessage(id=turn.message.id, content=turn.message.content,
                     additional_kwargs={"document_ids": list(turn.message.document_ids)})],
        "material_catalog": [d.model_dump(mode="json") for d in prepare_materials([], turn)],
    }
    return asyncio.run(
        prepare_context(
            state,
            ConversationExecutionContext(turn, turn_resources(turn, documents).read_materials),
            [],
        )
    )


def test_empty_document_selection_builds_chat_context(turn_factory):
    context = context_for(turn_factory())
    assert context.documents == [] and context.messages[0]["content"] == "你好"


def test_document_excerpt_fits_serialized_budget(turn_factory):
    document = TurnDocument(id="d1", filename="长文.docx", markdown="\\" * 40000)
    turn = turn_factory(documents=(document,))
    context = context_for(turn, (document,))
    assert len(context.model_dump_json()) <= 24000 and context.coverage_note
    assert len(document.markdown) == 40000


def test_current_message_is_never_dropped_for_json_escaping(turn_factory):
    with pytest.raises(AppError) as raised:
        context_for(turn_factory(content='"\\\n' * 4000))
    assert raised.value.code == "CONVERSATION_INPUT_TOO_LONG"


def test_previously_clipped_result_keeps_coverage_warning(turn_factory):
    history = [AIMessage(id="old", content="审核结果", additional_kwargs={
        "agent_result": "文" * 4000, "agent_result_truncated": True,
    })]
    context = context_for(turn_factory(), history=history)
    assert len(context.messages[0]["agent_result"]) == 4000 and context.coverage_note
