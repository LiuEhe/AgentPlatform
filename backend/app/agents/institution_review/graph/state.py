"""制度审核 LangGraph 共享状态。"""

from typing import TypedDict

from app.schemas.review import ReviewFinding, ReviewReference


class ReviewState(TypedDict, total=False):
    """在制度审核图节点之间传递的请求、依据和发现项。"""

    review_id: str
    title: str
    content: str
    clauses: list[str]
    references: list[ReviewReference]
    terminology_findings: list[ReviewFinding]
    conflict_findings: list[ReviewFinding]
    duplicate_findings: list[ReviewFinding]
    compliance_findings: list[ReviewFinding]
    findings: list[ReviewFinding]
    summary: str
