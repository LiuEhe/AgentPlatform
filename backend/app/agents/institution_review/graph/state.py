"""制度审核 LangGraph 共享状态。"""

from typing import TypedDict

from app.agents.institution_review.schemas import Clause, ClauseReview
from app.schemas.review import ReviewReference


class ReviewState(TypedDict, total=False):
    """保存文档、拆分条款、审核结果和各章节 Markdown。"""

    review_id: str
    title: str
    content: str
    clauses: list[Clause]
    clause_reviews: list[ClauseReview]
    references: list[ReviewReference]
    reference_names: list[str]
    terminology_markdown: str
    overview_markdown: str
    conflict_markdown: str
    suggestion_markdown: str
    report_markdown: str
