"""生成简述和冲突检测章节，并合并最终 Markdown 报告。"""

import json

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.institution_review.graph.state import ReviewState
from app.agents.institution_review.nodes._llm import invoke_markdown, invoke_structured
from app.agents.institution_review.prompts import REVIEW_PROMPTS
from app.agents.institution_review.schemas import ClauseReview, ReviewMode, ReviewOverviewOutput
from app.schemas.review import ReviewReference


def extract_reference_names(references: list[ReviewReference]) -> list[str]:
    """从真实检索引用中按首次出现顺序提取唯一文件名。"""
    names: list[str] = []
    seen: set[str] = set()
    for reference in references:
        name = (reference.document_name or "").strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def _report_data(
    reviews: list[ClauseReview],
    *,
    max_evidence_chars: int | None = 1200,
) -> list[dict[str, object]]:
    """整理条款发现项及其真实检索依据。"""
    rows: list[dict[str, object]] = []
    for review in reviews:
        for finding in review.findings:
            evidence = [
                {
                    "document_name": review.references[index - 1].document_name,
                    "content": review.references[index - 1].content[:max_evidence_chars],
                }
                for index in finding.reference_indexes
                if 1 <= index <= len(review.references)
            ]
            rows.append(
                {
                    "chapter": review.clause.chapter,
                    "section": review.clause.section,
                    "sequence": review.clause.sequence,
                    "article": review.clause.article,
                    "paragraph": review.clause.paragraph,
                    "item": review.clause.item,
                    "clause": review.clause.content,
                    "category": finding.category.value,
                    "severity": finding.severity.value,
                    "description": finding.description,
                    "evidence": evidence,
                }
            )
    return rows


def _escape_markdown_text(value: str) -> str:
    """转义 Markdown 列表中的分隔符。"""
    return (
        value.replace("\r", " ")
        .replace("\n", " ")
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
    )


def create_report_sections_node(model: BaseChatModel):
    """创建第一部分简述和第二部分冲突检测报告节点。"""

    async def generate(state: ReviewState) -> dict[str, str | list[str]]:
        references = state.get("references", [])
        is_standard = state.get("review_mode") == ReviewMode.STANDARD_DOCUMENT
        source_label = "上传标准文档" if is_standard else "知识库"
        names = extract_reference_names(references)
        if is_standard:
            names = [state["standard_name"]] if state.get("standard_name") else []
        rows = _report_data(
            state.get("clause_reviews", []),
            max_evidence_chars=None if is_standard else 1200,
        )
        review_data = json.dumps(rows, ensure_ascii=False)
        summary_data = json.dumps(
            [{key: value for key, value in row.items() if key != "evidence"} for row in rows],
            ensure_ascii=False,
        )
        source_data = json.dumps(names, ensure_ascii=False)

        overview = await invoke_structured(
            model,
            ReviewOverviewOutput,
            REVIEW_PROMPTS["overview"],
            f"制度标题：{state['title']}\n"
            f"已拆分并审核条款数：{len(state.get('clauses', []))}\n"
            f"逐条审查摘要：\n{summary_data}\n"
            f"全文术语检测结果：\n{state.get('terminology_markdown', '')}\n"
            "请按结构化格式只返回关注类别。",
        )
        actual_categories = {row["category"] for row in rows}
        focus = [
            name
            for name in ("冲突", "重复", "术语")
            if name in overview.focus and (name == "术语" or name in actual_categories)
        ]
        if is_standard and not rows:
            summary_text = "本次已完成与上传标准文档的逐条对比，未发现冲突或重复。"
        elif not references:
            summary_text = "本次未检索到可比对的知识库依据，冲突和重复暂无法核实。"
        elif not rows:
            summary_text = "本次已完成逐条检索，未发现有知识库依据的冲突或重复。"
        else:
            summary_text = f"本次发现 {len(rows)} 项需要关注的冲突或重复问题。"
        if focus:
            summary_text += f"关注类别：{'、'.join(focus)}。"
        else:
            summary_text += "模型未标记其他需要突出的类别。"
        if names:
            source_list = "\n".join(f"- {_escape_markdown_text(name)}" for name in names)
            source_title = "上传标准文档" if is_standard else "引用知识库文件"
            source_text = f"{source_title}：\n{source_list}"
        else:
            source_text = "本次逐条检索未返回可引用的知识库文件，因此冲突和重复无法核实。"
        overview_markdown = f"## 一. 简述\n\n{summary_text}\n\n{source_text}"

        if not rows and is_standard:
            conflict = (
                "| 章/节/条/款/项 | 问题类型 | 问题说明 | 严重程度 | 标准文档依据 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| — | 未发现 | 与上传标准文档对比，未发现冲突或重复。 | — | 已完成逐条对比 |"
            )
        elif not references:
            conflict = (
                "| 章/条/款/项 | 问题类型 | 问题说明 | 严重程度 | 知识库依据 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| — | 无法核实 | 未检索到可比对的知识库片段，"
                "无法判断是否存在冲突或重复。 | — | 无 |"
            )
        elif not rows:
            conflict = (
                "| 章/条/款/项 | 问题类型 | 问题说明 | 严重程度 | 知识库依据 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| — | 未发现 | 逐条审查未发现有知识库依据的冲突或重复。 | — | 已完成逐条检索 |"
            )
        else:
            conflict = await invoke_markdown(
                model,
                REVIEW_PROMPTS["conflicts"],
                f"逐条审查结构化结果：\n{review_data}\n{source_label}文件名：\n{source_data}",
                source_label=source_label,
            )
        return {
            "reference_names": names,
            "overview_markdown": overview_markdown,
            "conflict_markdown": f"## 二. 冲突检测\n\n{conflict}",
        }

    return generate


def assemble_report(state: ReviewState) -> dict[str, str]:
    """按固定顺序合并四个 Markdown 章节。"""
    sections = (
        state.get("overview_markdown", ""),
        state.get("conflict_markdown", ""),
        state.get("terminology_markdown", ""),
        state.get("suggestion_markdown", ""),
    )
    return {"report_markdown": "\n\n---\n\n".join(section.strip() for section in sections)}
