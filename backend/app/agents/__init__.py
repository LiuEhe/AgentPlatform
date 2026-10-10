"""发现智能体包并构建平台注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pkgutil import iter_modules
from typing import TYPE_CHECKING

from app.core.errors import AppError
from app.runtime.agent_runtime import AgentRegistry

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from app.infrastructure.ragflow.client import RagFlowClient


@dataclass(frozen=True)
class AgentBuildContext:
    """创建智能体所需的共享服务。"""

    model: BaseChatModel
    rag_client: RagFlowClient


def build_agent_registry(
    model: BaseChatModel,
    rag_client: RagFlowClient,
) -> AgentRegistry:
    """发现子包并调用各自的注册入口。"""
    registry = AgentRegistry()
    context = AgentBuildContext(model=model, rag_client=rag_client)
    modules = sorted(iter_modules(__path__), key=lambda module: module.name)

    for module_info in modules:
        if not module_info.ispkg or module_info.name.startswith("_"):
            continue
        package = import_module(f".{module_info.name}", package=__name__)
        register_agent = getattr(package, "register_agent", None)
        if not callable(register_agent):
            raise AppError(
                "AGENT_REGISTRATION_INVALID",
                f"智能体包 {module_info.name} 未实现注册入口",
                500,
            )
        register_agent(registry, context)

    return registry
