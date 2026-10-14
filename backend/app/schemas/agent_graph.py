"""Public response models for read-only agent graph descriptions."""

from pydantic import BaseModel


class AgentGraphNode(BaseModel):
    """A displayed node in an agent graph."""

    id: str
    label: str


class AgentGraphEdge(BaseModel):
    """An edge whose sources must all complete before its target can run."""

    sources: list[str]
    target: str


class AgentGraphResponse(BaseModel):
    """Static graph metadata returned to the frontend."""

    agent_id: str
    name: str
    nodes: list[AgentGraphNode]
    edges: list[AgentGraphEdge]
