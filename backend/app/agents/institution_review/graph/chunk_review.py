"""通过官方 Send 分发条款审核，并在子图内校验和汇合结果。"""

import asyncio

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from app.agents.institution_review.graph.state import (
    ChunkReviewInput,
    ChunkReviewOutput,
    ChunkReviewState,
    ChunkWorkerState,
)
from app.agents.institution_review.nodes.clause_review import (
    chunks_match_clauses,
    collect_chunk_reviews,
    create_knowledge_chunk_worker,
    create_standard_chunk_worker,
)
from app.agents.institution_review.schemas import ReviewMode
from app.core.errors import AppError
from app.core.observability import Observer
from app.infrastructure.ragflow.client import RagFlowClient


def dispatch_chunks(state: ChunkReviewState) -> dict[str, ReviewMode]:
    """校验既有拆分结果，只规范化模式，不重建分组。"""
    if not state.get("clauses"):
        raise AppError("REVIEW_CONTENT_EMPTY", "文档中没有可审核的条款内容", 422)
    error = AppError("GRAPH_CONFIGURATION_ERROR", "条款审核内部状态无效", 500)
    try:
        mode = ReviewMode(state.get("review_mode", ReviewMode.KNOWLEDGE_BASE))
    except (TypeError, ValueError) as exc:
        raise error from exc
    if not chunks_match_clauses(state["clauses"], state.get("chunks", [])):
        raise error
    if mode == ReviewMode.STANDARD_DOCUMENT and (
        not (state.get("standard_content") or "").strip()
        or not (state.get("standard_name") or "").strip()
    ):
        raise AppError("INVALID_AGENT_INPUT", "标准文档模式缺少标准名称或正文", 422)
    return {"review_mode": mode}


def route_chunks(state: ChunkReviewState) -> list[Send]:
    """每个执行组只向本轮模式的一个 worker 发送最小输入。"""
    standard = state["review_mode"] == ReviewMode.STANDARD_DOCUMENT
    target = "review_standard_chunk" if standard else "review_knowledge_chunk"
    sends = []
    for chunk in state["chunks"]:
        payload: ChunkWorkerState = {
            "title": state["title"],
            "review_mode": state["review_mode"],
            "chunk": chunk,
        }
        if standard:
            payload.update(
                standard_name=state["standard_name"],
                standard_content=state["standard_content"],
            )
        sends.append(Send(target, payload))
    return sends


def build_chunk_review_graph(
    model: BaseChatModel,
    rag_client: RagFlowClient | None,
    *,
    semaphore: asyncio.Semaphore,
    observer: Observer | None = None,
) -> CompiledStateGraph:
    """编译条款子图；调度和取消由 LangGraph 管理，资源额度由父图注入。"""
    graph = StateGraph(
        ChunkReviewState,
        input_schema=ChunkReviewInput,
        output_schema=ChunkReviewOutput,
    )
    graph.add_node("dispatch_chunks", dispatch_chunks)
    graph.add_node(
        "review_knowledge_chunk",
        create_knowledge_chunk_worker(model, rag_client, semaphore=semaphore, observer=observer),
        input_schema=ChunkWorkerState,
    )
    graph.add_node(
        "review_standard_chunk",
        create_standard_chunk_worker(model, semaphore=semaphore, observer=observer),
        input_schema=ChunkWorkerState,
    )
    graph.add_node("collect_chunk_reviews", collect_chunk_reviews)
    graph.add_edge(START, "dispatch_chunks")
    graph.add_conditional_edges(
        "dispatch_chunks",
        route_chunks,
        ["review_knowledge_chunk", "review_standard_chunk"],
    )
    graph.add_edge("review_knowledge_chunk", "collect_chunk_reviews")
    graph.add_edge("review_standard_chunk", "collect_chunk_reviews")
    graph.add_edge("collect_chunk_reviews", END)
    return graph.compile()
