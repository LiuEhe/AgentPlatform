"""制度审核图的固定节点流转顺序。"""

SPLIT_NODE = "split_clauses"
CLAUSE_REVIEW_NODE = "review_clauses"
TERMINOLOGY_NODE = "check_terminology"
REPORT_NODE = "generate_report_sections"
SUGGESTION_NODE = "generate_suggestions"
ASSEMBLE_NODE = "assemble_report"

REVIEW_NODE_ORDER = (
    SPLIT_NODE,
    CLAUSE_REVIEW_NODE,
    TERMINOLOGY_NODE,
    REPORT_NODE,
    SUGGESTION_NODE,
    ASSEMBLE_NODE,
)
