"""制度审核图的节点元信息、边关系和节点顺序。"""

START_NODE_ID = "START"
END_NODE_ID = "END"

SPLIT_NODE = "split_clauses"
CLAUSE_REVIEW_NODE = "review_clauses"
TERMINOLOGY_NODE = "check_terminology"
REPORT_NODE = "generate_report_sections"
SUGGESTION_NODE = "generate_suggestions"
ASSEMBLE_NODE = "assemble_report"

REVIEW_GRAPH_NODE_SPECS = (
    (START_NODE_ID, "开始"),
    (SPLIT_NODE, "条款拆分"),
    (CLAUSE_REVIEW_NODE, "条款审查"),
    (TERMINOLOGY_NODE, "术语检查"),
    (REPORT_NODE, "生成报告内容"),
    (SUGGESTION_NODE, "生成修改建议"),
    (ASSEMBLE_NODE, "组装报告"),
    (END_NODE_ID, "结束"),
)

REVIEW_GRAPH_EDGE_SPECS = (
    ((START_NODE_ID,), SPLIT_NODE),
    ((START_NODE_ID,), TERMINOLOGY_NODE),
    ((SPLIT_NODE,), CLAUSE_REVIEW_NODE),
    ((CLAUSE_REVIEW_NODE, TERMINOLOGY_NODE), REPORT_NODE),
    ((REPORT_NODE,), SUGGESTION_NODE),
    ((SUGGESTION_NODE,), ASSEMBLE_NODE),
    ((ASSEMBLE_NODE,), END_NODE_ID),
)

REVIEW_NODE_ORDER = tuple(
    node_id
    for node_id, _ in REVIEW_GRAPH_NODE_SPECS
    if node_id not in {START_NODE_ID, END_NODE_ID}
)
