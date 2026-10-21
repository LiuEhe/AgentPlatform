"""将制度审核工作流适配到平台智能体调用协议。"""

from collections.abc import Mapping
from typing import Self

from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.agents.institution_review.evaluation import project_evaluation
from app.agents.institution_review.graph.state import ReviewState
from app.agents.institution_review.schemas import ReviewMode
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentContext

INSTITUTION_REVIEW_AGENT_ID = "institution_review"


class InstitutionReviewInput(BaseModel):
    """制度审核智能体的输入数据。"""

    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    document_title: str | None = None
    review_mode: ReviewMode = ReviewMode.KNOWLEDGE_BASE
    standard_name: str | None = None
    standard_content: str | None = None

    @model_validator(mode="after")
    def validate_standard(self) -> Self:
        """拒绝缺少依据或与模式矛盾的标准输入。"""
        if self.review_mode == ReviewMode.STANDARD_DOCUMENT:
            if not (self.standard_name or "").strip() or not (self.standard_content or "").strip():
                raise ValueError("标准文档模式必须提供标准名称和正文")
        elif self.standard_name is not None or self.standard_content is not None:
            raise ValueError("知识库模式不能附带标准文档")
        return self


class InstitutionReviewAgent:
    """调用制度审核图并校验其 Markdown 输出。"""

    def __init__(
        self, graph: CompiledStateGraph, *, graph_config_factory=None, evaluation_sink=None
    ):
        self._graph = graph
        self._graph_config_factory = graph_config_factory
        self._evaluation_sink = evaluation_sink

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
            "review_mode": agent_input.review_mode,
        }
        if agent_input.document_title is not None:
            initial_state["document_title"] = agent_input.document_title
        if agent_input.review_mode == ReviewMode.STANDARD_DOCUMENT:
            initial_state["standard_name"] = agent_input.standard_name
            initial_state["standard_content"] = agent_input.standard_content
        config = self._graph_config_factory(context) if self._graph_config_factory else None
        result = await self._graph.ainvoke(initial_state, config=config)
        if self._evaluation_sink is not None:
            self._evaluation_sink(
                context.agent_id, context.invocation_id, project_evaluation(result)
            )
        report = result.get("report_markdown")
        if not isinstance(report, str) or not report.strip():
            raise AppError("AGENT_OUTPUT_INVALID", "制度审核未生成完整报告", 502)
        return report
