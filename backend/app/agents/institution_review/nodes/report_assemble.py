"""根据审核发现项组装简明结果报告。"""

from collections import Counter

from app.agents.institution_review.graph.state import ReviewState


def assemble_report(state: ReviewState) -> dict[str, str]:
    """生成基于实际发现数量和等级的确定性汇总。"""
    findings = state.get("findings", [])
    if not findings:
        return {"summary": "本次审核未发现明确问题；建议结合适用的内部制度和监管要求复核。"}

    severity_counts = Counter(item.severity.value for item in findings)
    categories = Counter(item.category.value for item in findings)
    severity_text = "、".join(
        f"{name} {count} 项"
        for name, count in (
            ("严重", severity_counts["critical"]),
            ("高", severity_counts["high"]),
            ("中", severity_counts["medium"]),
            ("低", severity_counts["low"]),
        )
        if count
    )
    category_names = {
        "terminology": "术语",
        "conflict": "冲突",
        "duplicate": "重复",
        "compliance": "合规",
    }
    category_text = "、".join(
        f"{category_names[name]} {count} 项" for name, count in categories.items()
    )
    return {"summary": f"本次审核发现 {len(findings)} 项问题（{severity_text}），类别包括：{category_text}。"}
