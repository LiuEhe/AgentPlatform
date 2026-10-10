"""制度审核智能体及其平台注册入口。"""

from app.agents import AgentBuildContext
from app.agents.institution_review.adapter import (
    INSTITUTION_REVIEW_AGENT_ID,
    InstitutionReviewAgent,
)
from app.agents.institution_review.graph.graph import build_review_graph
from app.runtime.agent_runtime import AgentRegistry


def register_agent(registry: AgentRegistry, context: AgentBuildContext) -> None:
    """创建并注册制度审核智能体。"""
    graph = build_review_graph(context.model, context.rag_client)
    registry.register(INSTITUTION_REVIEW_AGENT_ID, InstitutionReviewAgent(graph))
