"""制度审核完整任务模板，业务参数和输出 schema 仍留在节点。"""

from app.agents.institution_review.config import SYSTEM_PROMPT
from app.nodes.llm.prompts import PromptSpec

REVIEW_PROMPTS = {
    "knowledge-base-clause": PromptSpec(
        "institution-review/knowledge-base-clause",
        (
            ("system", SYSTEM_PROMPT),
            (
                "human",
                (
                    "审核任务：判断草稿条款与候选知识片段是否存在明确冲突或重复。"
                    "仅报告有片段依据的问题；冲突指要求相互矛盾，重复指要求实质相"
                    "同或覆盖。证据不足时返回空 findings。每项必须填写支"
                    "持该判断的知识片段编号 reference_indexes。"
                    "\n\n待分析数据：\n{content}"
                ),
            ),
        ),
    ),
    "standard-clause": PromptSpec(
        "institution-review/standard-clause",
        (
            ("system", SYSTEM_PROMPT),
            (
                "human",
                (
                    "审核任务：逐条对比草稿与标准文档，判断是否存在明确冲突或实质"
                    "重复。没有问题或依据不足时不输出发现。每项填写组内原始 cl"
                    "ause_sequence，并在 standard_exce"
                    "rpt 中逐字摘录支持判断的标准原文。不要把组号当条款编号。"
                    "\n\n待分析数据：\n{content}"
                ),
            ),
        ),
    ),
    "terminology": PromptSpec(
        "institution-review/terminology",
        (
            ("system", SYSTEM_PROMPT),
            (
                "human",
                (
                    "审核任务：检查全文中同一概念是否用词不一致、术语定义是否含混"
                    "或前后不一致。输出 Markdown 正文，不要重复章节标题"
                    "；逐项注明原文位置、术语和问题说明；没有问题时明确写明未发现"
                    "术语问题。\n\n待分析数据：\n{content}"
                ),
            ),
        ),
    ),
    "overview": PromptSpec(
        "institution-review/overview",
        (
            ("system", SYSTEM_PROMPT),
            (
                "human",
                (
                    "审核任务：为制度审查选择简述中的关注类别，不增加新的发现，只"
                    "从冲突、重复、术语三个固定类别中选择关注项；不得输出自由文本"
                    "、文件名或来源名称。\n\n待分析数据：\n{content}"
                ),
            ),
        ),
    ),
    "conflicts": PromptSpec(
        "institution-review/conflicts",
        (
            ("system", SYSTEM_PROMPT),
            (
                "human",
                (
                    "审核任务：将逐条审查结果汇总为 Markdown 表格，列出"
                    "原始章/节/条/款/项及序号、问题类型（冲突或重复）、问题说"
                    "明、严重程度和{source_label}依据。只能报告输入"
                    "中已有 findings，不能从原始条款推断新问题。不要输出"
                    "章节标题。\n\n待分析数据：\n{content}"
                ),
            ),
        ),
    ),
    "suggestions": PromptSpec(
        "institution-review/suggestions",
        (
            ("system", SYSTEM_PROMPT),
            (
                "human",
                (
                    "审核任务：根据已生成的冲突检测和术语检测结果，提出具体、克制"
                    "、可执行的制度修改建议。不要输出章节标题，不得引入新的审查发"
                    "现或输入中没有依据的事实；没有问题时明确说明无需基于本次检查"
                    "修改。\n\n待分析数据：\n{content}"
                ),
            ),
        ),
    ),
}
