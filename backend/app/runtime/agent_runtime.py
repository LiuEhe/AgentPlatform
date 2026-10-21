"""通过注册表按标识分发智能体调用。"""

import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from app.core.errors import AppError
from app.core.observability import NullObserver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentContext:
    """一次智能体调用的通用上下文。"""

    invocation_id: str
    agent_id: str


@dataclass(frozen=True)
class AgentExecution:
    """一次智能体调用的统一执行结果。"""

    invocation_id: str
    agent_id: str
    output: object


AgentInvoker = Callable[[str, Mapping[str, object]], Awaitable[AgentExecution]]


class AgentAdapter(Protocol):
    """定义智能体适配器的统一调用协议。"""

    async def invoke(
        self,
        payload: Mapping[str, object],
        context: AgentContext,
    ) -> object: ...


class AgentRegistry:
    """管理可由平台运行时调用的智能体适配器。"""

    def __init__(self) -> None:
        self._agents: dict[str, AgentAdapter] = {}

    def register(self, agent_id: str, agent: AgentAdapter) -> None:
        """注册一个智能体适配器。"""
        if not agent_id.strip():
            raise AppError("INVALID_AGENT_ID", "智能体标识不能为空", 500)
        if agent_id in self._agents:
            raise AppError("DUPLICATE_AGENT_ID", "智能体标识重复注册", 500)
        self._agents[agent_id] = agent

    def resolve(self, agent_id: str) -> AgentAdapter:
        """根据智能体标识获取适配器。"""
        agent = self._agents.get(agent_id)
        if agent is None:
            raise AppError("AGENT_NOT_FOUND", "请求的智能体未注册", 404)
        return agent


class AgentRuntime:
    """统一负责智能体分发、调用标识和执行日志。"""

    def __init__(self, registry: AgentRegistry, *, observer=None, execution_scope_factory=None):
        self._registry = registry
        self._observer = observer or NullObserver()
        self._execution_scope_factory = execution_scope_factory

    async def invoke(
        self,
        agent_id: str,
        payload: Mapping[str, object],
    ) -> AgentExecution:
        """按智能体标识执行一次调用。"""
        invocation_id = str(uuid4())
        context = AgentContext(invocation_id=invocation_id, agent_id=agent_id)
        try:
            agent = self._registry.resolve(agent_id)
            with self._observer.scope(
                agent_id,
                kind="agent",
                attributes={
                    "agent_id": agent_id,
                    "invocation_id": invocation_id,
                },
            ) as observation:
                scope = (
                    self._execution_scope_factory(context)
                    if self._execution_scope_factory
                    else nullcontext()
                )
                async with scope:
                    output = await agent.invoke(payload, context)
                observation.update(attributes={"status": "succeeded"})
        except AppError as exc:
            logger.warning(
                "agent_invoke_failed invocation_id=%s agent_id=%s code=%s",
                invocation_id,
                agent_id,
                exc.code,
            )
            raise
        except Exception as exc:
            logger.error(
                "agent_invoke_failed invocation_id=%s agent_id=%s error_type=%s",
                invocation_id,
                agent_id,
                type(exc).__name__,
            )
            raise AppError("AGENT_EXECUTION_FAILED", "智能体执行失败", 502) from exc

        logger.info(
            "agent_invoke_completed invocation_id=%s agent_id=%s",
            invocation_id,
            agent_id,
        )
        return AgentExecution(
            invocation_id=invocation_id,
            agent_id=agent_id,
            output=output,
        )
