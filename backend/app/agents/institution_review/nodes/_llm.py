"""制度审核节点共享的结构化模型调用逻辑。"""

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel

from app.agents.institution_review.config import SYSTEM_PROMPT
from app.core.errors import AppError
from app.nodes.llm.prompts import PromptSpec, invoke_prompt

logger = logging.getLogger(__name__)


async def invoke_structured[OutputT: BaseModel](
    model: BaseChatModel,
    output_schema: type[OutputT],
    task: str | PromptSpec,
    content: str,
) -> OutputT:
    """以 Pydantic 模型约束模型输出，并避免记录制度原文。"""
    try:
        spec = (
            task
            if isinstance(task, PromptSpec)
            else PromptSpec(
                "institution-review/custom",
                (
                    ("system", SYSTEM_PROMPT),
                    ("human", "审核任务：{task}\n\n待分析数据：\n{content}"),
                ),
            )
        )
        result = await invoke_prompt(
            model, spec, {"content": content, "task": task}, output_schema=output_schema
        )
    except Exception as exc:
        logger.warning("model_call_failed error_type=%s", type(exc).__name__)
        raise AppError("MODEL_ERROR", "模型服务调用失败或返回格式无效", 502) from exc

    if isinstance(result, output_schema):
        return result
    try:
        return output_schema.model_validate(result)
    except Exception as exc:
        logger.warning("model_output_invalid schema=%s", output_schema.__name__)
        raise AppError("MODEL_ERROR", "模型服务返回格式无效", 502) from exc


async def invoke_markdown(
    model: BaseChatModel,
    task: str | PromptSpec,
    content: str,
    *,
    source_label: str = "知识库",
) -> str:
    """调用模型生成 Markdown，并拒绝空或非文本结果。"""
    try:
        spec = (
            task
            if isinstance(task, PromptSpec)
            else PromptSpec(
                "institution-review/custom",
                (
                    ("system", SYSTEM_PROMPT),
                    ("human", "审核任务：{task}\n\n待分析数据：\n{content}"),
                ),
            )
        )
        result = await invoke_prompt(
            model,
            spec,
            {
                "content": content,
                "task": task,
                "source_label": source_label,
            },
        )
    except Exception as exc:
        logger.warning("model_call_failed error_type=%s", type(exc).__name__)
        raise AppError("MODEL_ERROR", "模型服务调用失败", 502) from exc

    value = getattr(result, "content", result)
    if isinstance(value, str):
        markdown = value.strip()
    elif isinstance(value, list):
        markdown = "\n".join(
            item["text"].strip()
            for item in value
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ).strip()
    else:
        markdown = ""

    if not markdown:
        raise AppError("MODEL_ERROR", "模型服务未返回有效 Markdown", 502)
    return markdown
