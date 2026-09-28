"""将制度正文拆分为可定位的条款。"""

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.institution_review.nodes._llm import invoke_structured
from app.agents.institution_review.schemas import ClauseList
from app.agents.institution_review.graph.state import ReviewState


def create_clause_split_node(model: BaseChatModel):
    """创建条款拆分节点。"""

    async def clause_split(state: ReviewState) -> dict[str, list[str]]:
        result = await invoke_structured(
            model,
            ClauseList,
            "按原文顺序拆分为独立条款或段落；尽量保留条款编号和原文，不改写内容。",
            f"标题：{state['title']}\n正文：\n{state['content']}",
        )
        clauses = [clause.strip() for clause in result.clauses if clause.strip()]
        return {"clauses": clauses or [state["content"]]}

    return clause_split
