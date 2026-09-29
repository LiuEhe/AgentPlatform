"""使用确定性规则将 Markdown 按章、节和条拆分。"""

import re

from app.agents.institution_review.graph.state import ReviewState
from app.agents.institution_review.schemas import Clause

_CHINESE_NUMBER = "一二三四五六七八九十百千万零〇两0-9"
_CHAPTER_PATTERN = re.compile(rf"^\s*(第[{_CHINESE_NUMBER}]+章)\s*(.*)$")
_SECTION_PATTERN = re.compile(rf"^\s*(第[{_CHINESE_NUMBER}]+节)\s*(.*)$")
_ARTICLE_PATTERN = re.compile(rf"^\s*(第[{_CHINESE_NUMBER}]+条)\s*(.*)$")
_PARAGRAPH_PATTERN = re.compile(r"^\s*([（(][一二三四五六七八九十百千万零〇两]+[）)])\s*(.*)$")
_ITEM_PATTERN = re.compile(r"^\s*([（(]\d+[）)]|\d+[、.．])\s*(.*)$")
_MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")


def _heading_text(line: str) -> str:
    """去除 Markdown 标题标记，保留标题正文。"""
    match = _MARKDOWN_HEADING_PATTERN.match(line)
    return match.group(1).strip() if match else line.strip()


def split_markdown_clauses(markdown: str, title: str | None = None) -> list[Clause]:
    """按章、节和条切分 Markdown，并保留未编号正文。"""
    clauses: list[Clause] = []
    chapter: str | None = None
    section: str | None = None
    article: str | None = None
    paragraph: str | None = None
    item: str | None = None
    article_heading: str | None = None
    paragraph_heading: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        content = "\n".join(line for line in current_lines if line.strip()).strip()
        if content:
            clauses.append(
                Clause(
                    chapter=chapter,
                    section=section,
                    article=article,
                    paragraph=paragraph,
                    item=item,
                    content=content,
                    sequence=len(clauses) + 1,
                )
            )
        current_lines.clear()

    first_content_line = True
    for raw_line in markdown.splitlines():
        line = _heading_text(raw_line)
        if not line:
            continue

        if first_content_line and title and line == title.strip():
            first_content_line = False
            continue
        first_content_line = False

        chapter_match = _CHAPTER_PATTERN.match(line)
        if chapter_match:
            flush()
            chapter = f"{chapter_match.group(1)} {chapter_match.group(2)}".strip()
            section = None
            article = None
            paragraph = None
            item = None
            article_heading = None
            paragraph_heading = None
            continue

        section_match = _SECTION_PATTERN.match(line)
        if section_match:
            flush()
            section = f"{section_match.group(1)} {section_match.group(2)}".strip()
            article = None
            paragraph = None
            item = None
            article_heading = None
            paragraph_heading = None
            continue

        article_match = _ARTICLE_PATTERN.match(line)
        if article_match:
            flush()
            article = f"{article_match.group(1)} {article_match.group(2)}".strip()
            paragraph = None
            item = None
            article_heading = line
            paragraph_heading = None
            if article_match.group(2).strip():
                current_lines.append(line)
            continue

        paragraph_match = _PARAGRAPH_PATTERN.match(line)
        if paragraph_match and article:
            flush()
            paragraph = paragraph_match.group(1)
            item = None
            paragraph_heading = line
            current_lines.extend(part for part in (article_heading, line) if part)
            continue

        item_match = _ITEM_PATTERN.match(line)
        if item_match and article:
            flush()
            item = item_match.group(1)
            current_lines.extend(
                part for part in (article_heading, paragraph_heading, line) if part
            )
            continue

        current_lines.append(line)

    flush()
    return clauses


def split_clauses(state: ReviewState) -> dict[str, list[Clause]]:
    """LangGraph 代码节点：将全文 Markdown 拆分为条款块。"""
    return {"clauses": split_markdown_clauses(state["content"], state.get("title"))}
