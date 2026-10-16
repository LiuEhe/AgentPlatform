"""构建并编译制度审核 LangGraph 工作流。"""

import asyncio

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.agents.institution_review.graph.edges import (
    ASSEMBLE_NODE,
    CLAUSE_REVIEW_NODE,
    END_NODE_ID,
    REPORT_NODE,
    REVIEW_GRAPH_EDGE_SPECS,
    REVIEW_NODE_ORDER,
    SPLIT_NODE,
    START_NODE_ID,
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
from app.core.config import DEFAULT_INSTITUTION_REVIEW_CONCURRENCY
from app.core.errors import AppError
from app.infrastructure.ragflow.client import RagFlowClient


def build_review_graph(
    model: BaseChatModel,
    rag_client: RagFlowClient | None,
    *,
    concurrency: int = DEFAULT_INSTITUTION_REVIEW_CONCURRENCY,
):
    """组装并行全文术语检查、逐条 RAG 审查和 Markdown 报告节点。"""
    if concurrency < 1:
        raise ValueError("制度审核并发数必须为正整数")
    semaphore = asyncio.Semaphore(concurrency)
    nodes = {
        SPLIT_NODE: split_clauses,
        CLAUSE_REVIEW_NODE: create_clause_review_node(model, rag_client, semaphore=semaphore),
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

    for source_ids, target_id in REVIEW_GRAPH_EDGE_SPECS:
        sources = [START if source_id == START_NODE_ID else source_id for source_id in source_ids]
        target = END if target_id == END_NODE_ID else target_id
        graph.add_edge(sources[0] if len(sources) == 1 else sources, target)
    return graph.compile()
