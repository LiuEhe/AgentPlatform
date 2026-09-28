"""创建 LangChain 聊天模型客户端。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.core.errors import AppError


def build_chat_model(settings: Settings) -> BaseChatModel:
    """创建 OpenAI 兼容聊天模型，可连接官方服务或兼容网关。"""
    if settings.llm_provider != "openai_compatible":
        raise AppError("MODEL_NOT_CONFIGURED", "当前模型提供方暂不支持", 503)
    if not settings.llm_model or not settings.llm_api_key:
        raise AppError("MODEL_NOT_CONFIGURED", "模型名称或 API Key 未配置", 503)

    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=60,
        max_retries=1,
    )
