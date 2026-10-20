"""组织完整原文索引；仅允许当前会话文档和用户消息成为材料。"""

from collections.abc import Mapping

from app.agents.conversation_assistant.schemas import MaterialRef
from app.core.errors import AppError
from app.schemas.conversation_turn import ConversationTurnInput

Materials = dict[tuple[str, str], tuple[str, str]]


def prepare_materials(turn: ConversationTurnInput) -> Materials:
    materials = {
        ("document", document.id): (document.filename, document.markdown)
        for document in turn.documents
    }
    materials.update(
        {
            ("user_message", message.id): ("粘贴正文", message.content)
            for message in turn.messages
            if message.role == "user"
        }
    )
    return materials


def resolve_material(
    materials: Mapping[tuple[str, str], tuple[str, str]],
    ref: MaterialRef,
) -> tuple[str, str]:
    material = materials.get((ref.kind, ref.id))
    if material is None:
        raise AppError("MATERIAL_NOT_FOUND", "会话材料不存在，请重新选择", 404)
    return material
