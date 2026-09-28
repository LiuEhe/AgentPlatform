"""应用层模型服务构造入口。"""

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import Settings
from app.infrastructure.llm.chat_model import build_chat_model


def create_llm_service(settings: Settings) -> BaseChatModel:
    """基于应用配置创建 LangChain 聊天模型。"""
    return build_chat_model(settings)
