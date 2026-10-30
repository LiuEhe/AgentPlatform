"""Read-only agent metadata routes."""

from fastapi import APIRouter, Request

from app.core.errors import AppError
from app.schemas.agent import AgentMetadata
from app.schemas.agent_graph import AgentGraphResponse
from app.services.agent_graph_service import get_agent_graph

router = APIRouter(tags=["agents"])


@router.get("/agents", response_model=list[AgentMetadata])
async def list_agents(request: Request) -> list[AgentMetadata]:
    service = getattr(request.app.state, "agent_catalog_service", None)
    if service is None:
        raise AppError("SERVICE_NOT_READY", "智能体目录尚未就绪", 503)
    return await service.list_agents()


@router.get("/agents/{agent_id}/graph", response_model=AgentGraphResponse)
def read_agent_graph(agent_id: str) -> AgentGraphResponse:
    """Return the static node and edge description for an agent."""
    return get_agent_graph(agent_id)
