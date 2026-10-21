"""发现智能体包并构建平台注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pkgutil import iter_modules
from typing import TYPE_CHECKING

from app.core.config import DEFAULT_INSTITUTION_REVIEW_CONCURRENCY
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentInvoker, AgentRegistry, AgentRuntime

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from app.infrastructure.ragflow.client import RagFlowClient


@dataclass(frozen=True)
class AgentBuildContext:
    """创建智能体所需的共享服务。"""

    model: BaseChatModel
    rag_client: RagFlowClient | None = None
    institution_review_concurrency: int = DEFAULT_INSTITUTION_REVIEW_CONCURRENCY
    invoke_agent: AgentInvoker | None = None
    conversation_max_review_chars: int = 50000
    conversation_knowledge_base_configured: bool = False
    observer: object | None = None
    graph_config_factory: object | None = None
    evaluation_sink: object | None = None


def build_agent_registry(
    model: BaseChatModel,
    rag_client: RagFlowClient | None = None,
    *,
    institution_review_concurrency: int = DEFAULT_INSTITUTION_REVIEW_CONCURRENCY,
    registry: AgentRegistry | None = None,
    invoke_agent: AgentInvoker | None = None,
    conversation_max_review_chars: int = 50000,
    conversation_knowledge_base_configured: bool | None = None,
    observer=None,
    graph_config_factory=None,
    evaluation_sink=None,
) -> AgentRegistry:
    """发现子包并调用各自的注册入口。"""
    registry = registry if registry is not None else AgentRegistry()
    # 注册阶段只绑定调用能力；全部注册完成后再执行，避免依赖包发现顺序。
    invoke_agent = invoke_agent if invoke_agent is not None else AgentRuntime(registry).invoke
    context = AgentBuildContext(
        model=model,
        observer=observer,
        graph_config_factory=graph_config_factory,
        evaluation_sink=evaluation_sink,
        rag_client=rag_client,
        institution_review_concurrency=institution_review_concurrency,
        invoke_agent=invoke_agent,
        conversation_max_review_chars=conversation_max_review_chars,
        conversation_knowledge_base_configured=(
            rag_client is not None
            if conversation_knowledge_base_configured is None
            else conversation_knowledge_base_configured
        ),
    )
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
