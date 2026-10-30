"""读取持久智能体目录；执行能力仍由代码注册表确定。"""

from collections.abc import Awaitable, Callable

from app.schemas.agent import AgentMetadata


class AgentCatalogService:
    def __init__(self, list_agents: Callable[[], Awaitable[list[dict]]]):
        self._list_agents = list_agents

    async def list_agents(self) -> list[AgentMetadata]:
        return [AgentMetadata(**row) for row in await self._list_agents()]
