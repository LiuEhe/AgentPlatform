"""公共有界历史摘要；输入历史和提示由调用 Agent 选择。"""

import json
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError
from app.nodes.llm.context import ContextBudgetError, ContextItem, build_context
from app.nodes.llm.prompts import PromptSpec, invoke_prompt


@dataclass(frozen=True)
class MemoryPolicy:
    trigger_messages: int = 8
    trigger_chars: int = 12000
    summary_max_chars: int = 3000
    chunk_chars: int = 12000
    recent_turns: int = 2


@dataclass(frozen=True)
class SummaryResult:
    text: str
    through_sequence: int
    removed_message_ids: tuple[str, ...]


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, pattern=r"\S")


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _item(message):
    return {
        "id": message.id, "role": message.type,
        "sequence": message.additional_kwargs["sequence"],
        "run_id": message.additional_kwargs["run_id"], "offset": 0,
        "content": message.content,
    }


def needs_summary(messages: Sequence[BaseMessage], *, policy: MemoryPolicy) -> bool:
    return len(messages) > policy.trigger_messages or len(_json([
        _item(message) for message in messages
    ])) > policy.trigger_chars


def _chunks(items, limit):
    accepted = []
    for item in items:
        text, offset = str(item["content"]), 0
        while offset < len(text):
            candidate = ContextItem(
                "messages",
                dict(item, content=text[offset:], offset=item["offset"] + offset),
                len(accepted),
                "content",
            )
            result = build_context(
                {"messages": []}, required_items=accepted, optional_items=[candidate],
                max_chars=limit, omission_note="",
            )
            values = result.payload["messages"]
            if len(values) == len(accepted) or not values[-1]["content"]:
                if not accepted:
                    raise ContextBudgetError("摘要片段元数据超过预算")
                yield {"messages": [item.value for item in accepted], "coverage_note": ""}
                accepted = []
                continue
            fragment = values[-1]
            accepted.append(ContextItem("messages", fragment, len(accepted)))
            offset += len(fragment["content"])
            if offset < len(text):
                yield result.payload
                accepted = []
    if accepted:
        yield {"messages": [item.value for item in accepted], "coverage_note": ""}


async def summarize_history(
    model: BaseChatModel, messages: Sequence[BaseMessage], *, previous_summary: str,
    covered_sequence: int, policy: MemoryPolicy, prompt: PromptSpec,
) -> SummaryResult:
    selected = [m for m in messages if m.additional_kwargs["sequence"] > covered_sequence]
    summary = previous_summary
    try:
        pending = deque(
            (history, policy.chunk_chars)
            for history in _chunks([_item(message) for message in selected], policy.chunk_chars)
        )
        while pending:
            history, limit = pending.popleft()
            try:
                value = await invoke_prompt(
                    model, prompt, {"content": _json({"summary": summary, "history": history})},
                    output_schema=SummaryOutput, max_input_chars=24000,
                )
            except ContextBudgetError:
                # Resolved templates and the outer JSON envelope add escaping overhead.
                # The guard runs before the model; split only this rejected fragment.
                smaller = limit // 2
                if smaller < 1:
                    raise
                fragments = list(_chunks(history["messages"], smaller))
                pending.extendleft((fragment, smaller) for fragment in reversed(fragments))
                continue
            output = SummaryOutput.model_validate(value)
            if len(_json(output.model_dump())) > policy.summary_max_chars:
                raise ValueError("Summary exceeds budget")
            summary = output.text
    except ContextBudgetError as exc:
        raise AppError("CONVERSATION_INPUT_TOO_LONG", "摘要请求超过上下文预算", 422) from exc
    except Exception as exc:
        raise AppError("MODEL_ERROR", "会话摘要失败，请稍后重试", 502) from exc
    return SummaryResult(
        summary, max((m.additional_kwargs["sequence"] for m in selected), default=covered_sequence),
        tuple(m.id for m in selected),
    )
