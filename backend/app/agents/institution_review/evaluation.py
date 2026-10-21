"""根据审核结构化发现评价定位与依据，避免只比较 Markdown。"""


def project_evaluation(state):
    findings = []
    unsupported = 0
    for review in state.get("clause_reviews", []):
        for finding in review.findings:
            valid = bool(finding.reference_indexes) and all(
                1 <= idx <= len(review.references) for idx in finding.reference_indexes
            )
            unsupported += int(not valid)
            findings.append(
                {
                    "category": finding.category.value,
                    "sequence": review.clause.sequence,
                    "evidence_valid": valid,
                }
            )
    report = state.get("report_markdown", "")
    headings = ("## 一. 简述", "## 二. 冲突检测", "## 三. 术语检测", "## 四. 修改建议")
    return {
        "finding_count": len(findings),
        "unsupported_findings": unsupported,
        "findings": findings,
        "sections_complete": all(h in report for h in headings),
        "categories": sorted({f["category"] for f in findings}),
        "sequences": sorted({f["sequence"] for f in findings}),
    }


def evaluate_case(expected, actual):
    return [
        {
            "name": key,
            "value": float(actual.get(key) == value),
            "comment": "matched" if actual.get(key) == value else "mismatch",
        }
        for key, value in expected.items()
    ]
