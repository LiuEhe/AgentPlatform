"""Read-only agent metadata routes."""

from fastapi import APIRouter

from app.schemas.agent_graph import AgentGraphResponse
from app.services.agent_graph_service import get_agent_graph

router = APIRouter(tags=["agents"])


@router.get("/agents/{agent_id}/graph", response_model=AgentGraphResponse)
def read_agent_graph(agent_id: str) -> AgentGraphResponse:
    """Return the static node and edge description for an agent."""
    return get_agent_graph(agent_id)
