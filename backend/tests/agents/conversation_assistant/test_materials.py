import pytest
from pydantic import ValidationError

from app.agents.conversation_assistant.nodes.material_prepare import (
    prepare_materials,
    resolve_material,
)
from app.core.errors import AppError
from app.schemas.conversation_turn import MaterialReference, TurnDocument


def test_pasted_catalog_preserves_id_and_original_length(turn_factory):
    text = "草稿\n第一条  正文保留空白"
    turn = turn_factory(content=text)
    descriptor = resolve_material(
        prepare_materials([], turn), MaterialReference(kind="user_message", id="m1")
    )
    assert descriptor.chars == len(text) and turn.message.content == text


def test_assistant_message_cannot_be_current_user_material(turn_factory):
    with pytest.raises(ValidationError):
        turn_factory(role="assistant")


def test_cross_session_document_rejected(turn_factory):
    with pytest.raises(AppError):
        resolve_material(
            prepare_materials([], turn_factory()), MaterialReference(kind="document", id="other")
        )


def test_same_filename_materials_use_ids(turn_factory):
    documents = (
        TurnDocument(id="a", filename="同名.docx", markdown="草稿原文"),
        TurnDocument(id="b", filename="同名.docx", markdown="标准原文"),
    )
    catalog = prepare_materials([], turn_factory(documents=documents))
    assert resolve_material(catalog, MaterialReference(kind="document", id="a")).ref.id == "a"
    assert resolve_material(catalog, MaterialReference(kind="document", id="b")).ref.id == "b"
