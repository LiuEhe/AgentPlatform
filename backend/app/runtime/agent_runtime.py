"""封装制度审核 LangGraph 的统一执行入口。"""

import logging
from uuid import uuid4

from langgraph.graph.state import CompiledStateGraph

from app.agents.institution_review.graph.state import ReviewState
from app.core.errors import AppError

logger = logging.getLogger(__name__)


class AgentRuntime:
    """通过编译后的制度审核图执行一次同步审核。"""

    def __init__(self, graph: CompiledStateGraph) -> None:
        self._graph = graph

    async def review(self, title: str, content: str) -> str:
        """执行审核图并返回最终 Markdown 报告。"""
        review_id = str(uuid4())
        initial_state: ReviewState = {
            "review_id": review_id,
            "title": title,
            "content": content,
        }
        try:
            result = await self._graph.ainvoke(initial_state)
        except AppError as exc:
            logger.warning(
                "review_failed review_id=%s code=%s",
                review_id,
                exc.code,
            )
            raise
        except Exception as exc:
            logger.error(
                "review_failed review_id=%s error_type=%s",
                review_id,
                type(exc).__name__,
            )
            raise AppError("REVIEW_FAILED", "制度审核流程执行失败", 502) from exc

        if not result.get("report_markdown"):
            raise AppError("REVIEW_FAILED", "制度审核流程未生成完整报告", 502)
        logger.info("review_completed review_id=%s", review_id)
        return result["report_markdown"]
