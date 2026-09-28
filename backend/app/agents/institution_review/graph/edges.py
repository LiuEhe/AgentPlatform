"""制度审核图的固定节点流转顺序。"""

REVIEW_NODE_ORDER = (
    "retrieve_context",
    "split_clauses",
    "check_terminology",
    "check_conflicts",
    "check_duplicates",
    "check_compliance",
    "reduce_findings",
    "generate_suggestions",
    "assemble_report",
)
