"""构建并编译制度审核 LangGraph 工作流。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.agents.institution_review.graph.edges import REVIEW_NODE_ORDER
from app.agents.institution_review.graph.state import ReviewState
from app.agents.institution_review.nodes.clause_split import create_clause_split_node
from app.agents.institution_review.nodes.compliance_check import create_compliance_check
from app.agents.institution_review.nodes.conflict_check import create_conflict_check
from app.agents.institution_review.nodes.conflict_reduce import reduce_findings
from app.agents.institution_review.nodes.duplicate_check import create_duplicate_check
from app.agents.institution_review.nodes.report_assemble import assemble_report
from app.agents.institution_review.nodes.suggestion_generate import create_suggestion_node
from app.agents.institution_review.nodes.terminology_check import create_terminology_check
from app.core.errors import AppError
from app.infrastructure.ragflow.client import RagFlowClient
from app.schemas.review import ReviewReference


def build_review_graph(model: BaseChatModel, rag_client: RagFlowClient):
    """组装检索、条款检查、建议生成和报告节点。"""

    async def retrieve_context(state: ReviewState) -> dict[str, list[ReviewReference]]:
        query = f"{state['title']}\n{state['content'][:8000]}"
        chunks = await rag_client.retrieve(query, top_k=8)
        references = [
            ReviewReference(
                content=chunk.content[:3000],
                document_name=chunk.document_name,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                url=chunk.url,
                similarity=chunk.similarity,
            )
            for chunk in chunks
        ]
        return {"references": references}

    nodes = {
        "retrieve_context": retrieve_context,
        "split_clauses": create_clause_split_node(model),
        "check_terminology": create_terminology_check(model),
        "check_conflicts": create_conflict_check(model),
        "check_duplicates": create_duplicate_check(model),
        "check_compliance": create_compliance_check(model),
        "reduce_findings": reduce_findings,
        "generate_suggestions": create_suggestion_node(model),
        "assemble_report": assemble_report,
    }
    if tuple(nodes) != REVIEW_NODE_ORDER:
        raise AppError("GRAPH_CONFIGURATION_ERROR", "制度审核流程节点配置不一致", 500)

    graph = StateGraph(ReviewState)
    for name, node in nodes.items():
        graph.add_node(name, node)
    graph.add_edge(START, REVIEW_NODE_ORDER[0])
    for current, following in zip(REVIEW_NODE_ORDER, REVIEW_NODE_ORDER[1:]):
        graph.add_edge(current, following)
    graph.add_edge(REVIEW_NODE_ORDER[-1], END)
    return graph.compile()
