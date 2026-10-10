"""将制度审核工作流适配到平台智能体调用协议。"""

from collections.abc import Mapping

from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field, ValidationError

from app.agents.institution_review.graph.state import ReviewState
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentContext

INSTITUTION_REVIEW_AGENT_ID = "institution_review"


class InstitutionReviewInput(BaseModel):
    """制度审核智能体的输入数据。"""

    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


class InstitutionReviewAgent:
    """调用制度审核图并校验其 Markdown 输出。"""

    def __init__(self, graph: CompiledStateGraph) -> None:
        self._graph = graph

    async def invoke(
        self,
        payload: Mapping[str, object],
        context: AgentContext,
    ) -> str:
        """将通用调用数据转换为制度审核图状态。"""
        try:
            agent_input = InstitutionReviewInput.model_validate(payload)
        except ValidationError as exc:
            raise AppError("INVALID_AGENT_INPUT", "制度审核输入无效", 422) from exc

        initial_state: ReviewState = {
            "review_id": context.invocation_id,
            "title": agent_input.title,
            "content": agent_input.content,
        }
        result = await self._graph.ainvoke(initial_state)
        report = result.get("report_markdown")
        if not isinstance(report, str) or not report.strip():
            raise AppError("AGENT_OUTPUT_INVALID", "制度审核未生成完整报告", 502)
        return report
