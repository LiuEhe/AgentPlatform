"""构建并编译制度审核 LangGraph 工作流。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.agents.institution_review.graph.edges import (
    ASSEMBLE_NODE,
    CLAUSE_REVIEW_NODE,
    REPORT_NODE,
    REVIEW_NODE_ORDER,
    SPLIT_NODE,
    SUGGESTION_NODE,
    TERMINOLOGY_NODE,
)
from app.agents.institution_review.graph.state import ReviewState
from app.agents.institution_review.nodes.clause_review import create_clause_review_node
from app.agents.institution_review.nodes.clause_split import split_clauses
from app.agents.institution_review.nodes.report_assemble import (
    assemble_report,
    create_report_sections_node,
)
from app.agents.institution_review.nodes.suggestion_generate import create_suggestion_node
from app.agents.institution_review.nodes.terminology_check import create_terminology_check
from app.core.errors import AppError
from app.infrastructure.ragflow.client import RagFlowClient


def build_review_graph(model: BaseChatModel, rag_client: RagFlowClient):
    """组装并行全文术语检查、逐条 RAG 审查和 Markdown 报告节点。"""
    nodes = {
        SPLIT_NODE: split_clauses,
        CLAUSE_REVIEW_NODE: create_clause_review_node(model, rag_client),
        TERMINOLOGY_NODE: create_terminology_check(model),
        REPORT_NODE: create_report_sections_node(model),
        SUGGESTION_NODE: create_suggestion_node(model),
        ASSEMBLE_NODE: assemble_report,
    }
    if set(nodes) != set(REVIEW_NODE_ORDER):
        raise AppError("GRAPH_CONFIGURATION_ERROR", "制度审核流程节点配置不一致", 500)

    graph = StateGraph(ReviewState)
    for name, node in nodes.items():
        graph.add_node(name, node)

    graph.add_edge(START, SPLIT_NODE)
    graph.add_edge(START, TERMINOLOGY_NODE)
    graph.add_edge(SPLIT_NODE, CLAUSE_REVIEW_NODE)
    graph.add_edge([CLAUSE_REVIEW_NODE, TERMINOLOGY_NODE], REPORT_NODE)
    graph.add_edge(REPORT_NODE, SUGGESTION_NODE)
    graph.add_edge(SUGGESTION_NODE, ASSEMBLE_NODE)
    graph.add_edge(ASSEMBLE_NODE, END)
    return graph.compile()
