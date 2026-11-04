"""组织材料目录；正文通过本轮已授权能力按引用读取。"""

from collections.abc import Sequence

from app.core.errors import AppError
from app.schemas.conversation_turn import (
    ConversationTurnInput,
    MaterialDescriptor,
    MaterialReference,
)


def prepare_materials(
    catalog: Sequence[dict], turn: ConversationTurnInput
) -> list[MaterialDescriptor]:
    items = {
        (d["ref"]["kind"], d["ref"]["id"]): MaterialDescriptor.model_validate(d) for d in catalog
    }
    for descriptor in turn.material_catalog:
        items[(descriptor.ref.kind, descriptor.ref.id)] = descriptor
    ref = MaterialReference(kind="user_message", id=turn.message.id)
    items[(ref.kind, ref.id)] = MaterialDescriptor(
        ref=ref, title="粘贴正文", chars=len(turn.message.content), sequence=turn.message.sequence,
    )
    return list(items.values())


def resolve_material(
    catalog: Sequence[MaterialDescriptor], ref: MaterialReference
) -> MaterialDescriptor:
    for descriptor in catalog:
        if descriptor.ref == ref:
            return descriptor
    raise AppError("MATERIAL_NOT_FOUND", "会话材料不存在，请重新选择", 404)
