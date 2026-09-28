"""为没有可执行建议的审核发现项补充建议。"""

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from app.agents.institution_review.nodes._llm import invoke_structured
from app.agents.institution_review.graph.state import ReviewState
from app.schemas.review import ReviewFinding


class SuggestionList(BaseModel):
    """按发现项顺序返回修改建议。"""

    suggestions: list[str] = Field(default_factory=list)


def create_suggestion_node(model: BaseChatModel):
    """创建修改建议生成节点。"""

    async def generate(state: ReviewState) -> dict[str, list[ReviewFinding]]:
        findings = state.get("findings", [])
        if not findings:
            return {"findings": []}

        items = [
            {
                "index": index,
                "category": item.category.value,
                "clause": item.clause,
                "description": item.description,
                "current_suggestion": item.suggestion,
            }
            for index, item in enumerate(findings)
        ]
        result = await invoke_structured(
            model,
            SuggestionList,
            "为每一项提供具体、克制且可执行的修改建议。按输入顺序逐项返回，不增加新发现。",
            f"制度标题：{state['title']}\n发现项：\n{items}",
        )
        updated = [
            finding.model_copy(
                update={
                    "suggestion": (
                        result.suggestions[index].strip()
                        if index < len(result.suggestions) and result.suggestions[index].strip()
                        else finding.suggestion
                    )
                }
            )
            for index, finding in enumerate(findings)
        ]
        return {"findings": updated}

    return generate
