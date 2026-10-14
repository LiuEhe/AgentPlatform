"""Application use case for retrieving a static agent graph description."""

from app.agents.institution_review.adapter import INSTITUTION_REVIEW_AGENT_ID
from app.agents.institution_review.graph.edges import (
    REVIEW_GRAPH_EDGE_SPECS,
    REVIEW_GRAPH_NODE_SPECS,
)
from app.core.errors import AppError
from app.schemas.agent_graph import AgentGraphEdge, AgentGraphNode, AgentGraphResponse

INSTITUTION_REVIEW_AGENT_NAME = "制度审核助手"


def get_agent_graph(agent_id: str) -> AgentGraphResponse:
    """Return static graph metadata for a registered agent ID."""
    if agent_id != INSTITUTION_REVIEW_AGENT_ID:
        raise AppError("AGENT_GRAPH_NOT_FOUND", "未找到该智能体的流程图", 404)

    return AgentGraphResponse(
        agent_id=INSTITUTION_REVIEW_AGENT_ID,
        name=INSTITUTION_REVIEW_AGENT_NAME,
        nodes=[
            AgentGraphNode(id=node_id, label=label)
            for node_id, label in REVIEW_GRAPH_NODE_SPECS
        ],
        edges=[
            AgentGraphEdge(sources=list(sources), target=target)
            for sources, target in REVIEW_GRAPH_EDGE_SPECS
        ],
    )
