"""按实际 JSON 大小构建模型上下文，不理解任何 Agent 业务参数。"""

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class ContextItem:
    collection: str
    value: dict[str, object]
    order: int
    truncate_field: str | None = None
    already_truncated: bool = False


@dataclass(frozen=True)
class ContextBuildResult:
    payload: dict[str, object]
    omitted: bool


class ContextBudgetError(ValueError):
    pass


def build_context(
    base_payload: Mapping[str, object],
    *,
    required_items: Sequence[ContextItem],
    optional_items: Sequence[ContextItem],
    max_chars: int,
    omission_note: str,
) -> ContextBuildResult:
    base = deepcopy(dict(base_payload))
    accepted: list[tuple[ContextItem, dict[str, object]]] = []

    def render(items, note):
        result = deepcopy(base)
        for item, value in sorted(items, key=lambda pair: pair[0].order):
            result.setdefault(item.collection, []).append(value)
        result["coverage_note"] = note
        return result

    def fits(items):
        # 先预留省略说明的开销，避免裁剪后追加说明再次突破预算。
        payload = render(items, omission_note)
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) <= max_chars

    accepted.extend((item, deepcopy(item.value)) for item in required_items)
    if not fits(accepted):
        raise ContextBudgetError("必需上下文超过序列化预算")
    omitted = any(item.already_truncated for item in required_items)
    for item in optional_items:
        value = deepcopy(item.value)
        if fits([*accepted, (item, value)]):
            accepted.append((item, value))
            omitted |= item.already_truncated
            continue
        omitted = True
        field = item.truncate_field
        if field is None or not isinstance(value.get(field), str):
            continue
        text = value[field]
        value[field] = ""
        if not fits([*accepted, (item, value)]):
            continue
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            value[field] = text[:middle]
            if fits([*accepted, (item, value)]):
                low = middle
            else:
                high = middle - 1
        value[field] = text[:low]
        accepted.append((item, value))
    result = render(accepted, omission_note if omitted else "")
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > max_chars:
        raise ContextBudgetError("上下文超过序列化预算")
    return ContextBuildResult(result, omitted)
