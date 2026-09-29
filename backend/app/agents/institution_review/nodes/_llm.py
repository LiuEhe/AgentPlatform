"""制度审核节点共享的结构化模型调用逻辑。"""

import logging
from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel

from app.agents.institution_review.config import SYSTEM_PROMPT
from app.core.errors import AppError

logger = logging.getLogger(__name__)
OutputT = TypeVar("OutputT", bound=BaseModel)


async def invoke_structured(
    model: BaseChatModel,
    output_schema: type[OutputT],
    task: str,
    content: str,
) -> OutputT:
    """以 Pydantic 模型约束模型输出，并避免记录制度原文。"""
    structured_model = model.with_structured_output(output_schema)
    try:
        result = await structured_model.ainvoke(
            [
                ("system", SYSTEM_PROMPT),
                ("human", f"审核任务：{task}\n\n待分析数据：\n{content}"),
            ]
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


async def invoke_markdown(model: BaseChatModel, task: str, content: str) -> str:
    """调用模型生成 Markdown，并拒绝空或非文本结果。"""
    try:
        result = await model.ainvoke(
            [
                ("system", SYSTEM_PROMPT),
                ("human", f"审核任务：{task}\n\n待分析数据：\n{content}"),
            ]
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
