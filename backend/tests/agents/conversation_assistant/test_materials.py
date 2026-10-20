import pytest

from app.agents.conversation_assistant.nodes.material_prepare import (
    prepare_materials,
    resolve_material,
)
from app.agents.conversation_assistant.schemas import MaterialRef
from app.core.errors import AppError
from app.schemas.conversation_turn import TurnDocument


def test_resolve_pasted_user_message_preserves_text(turn_factory):
    text = "草稿\n第一条  正文保留空白"
    materials = prepare_materials(turn_factory(content=text))
    assert resolve_material(materials, MaterialRef(kind="user_message", id="m1"))[1] == text


def test_assistant_message_cannot_be_material(turn_factory):
    materials = prepare_materials(turn_factory(role="assistant"))
    with pytest.raises(AppError):
        resolve_material(materials, MaterialRef(kind="user_message", id="m1"))


def test_cross_session_document_rejected(turn_factory):
    with pytest.raises(AppError):
        resolve_material(
            prepare_materials(turn_factory()), MaterialRef(kind="document", id="other")
        )


def test_same_filename_materials_use_ids(turn_factory):
    documents = (
        TurnDocument(id="a", filename="同名.docx", markdown="草稿原文"),
        TurnDocument(id="b", filename="同名.docx", markdown="标准原文"),
    )
    materials = prepare_materials(turn_factory(documents=documents))
    assert resolve_material(materials, MaterialRef(kind="document", id="a"))[1] == "草稿原文"
    assert resolve_material(materials, MaterialRef(kind="document", id="b"))[1] == "标准原文"
