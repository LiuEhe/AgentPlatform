"""合并制度检查中的重复发现项。"""

from app.agents.institution_review.graph.state import ReviewState
from app.schemas.review import ReviewFinding


def reduce_findings(state: ReviewState) -> dict[str, list[ReviewFinding]]:
    """按类别、条款和问题描述去除完全重复的发现项。"""
    unique: list[ReviewFinding] = []
    seen: set[tuple[str, str, str]] = set()
    for key in (
        "terminology_findings",
        "conflict_findings",
        "duplicate_findings",
        "compliance_findings",
    ):
        for finding in state.get(key, []):
            identity = (
                finding.category.value,
                " ".join(finding.clause.casefold().split()),
                " ".join(finding.description.casefold().split()),
            )
            if identity not in seen:
                seen.add(identity)
                unique.append(finding)
    return {"findings": unique}
