"""使用确定性规则将 Markdown 按章、节和条拆分。"""

import re

from app.agents.institution_review.graph.state import ReviewState
from app.agents.institution_review.schemas import Clause, ReviewChunk, ReviewMode

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


def group_clauses(clauses: list[Clause], *, max_chunks: int = 30) -> list[ReviewChunk]:
    """按正文长度尽量均衡地合并相邻条款，不截断单条正文。"""
    if max_chunks <= 0:
        raise ValueError("分组上限必须为正整数")
    group_count = min(max_chunks, len(clauses))
    remaining_chars = sum(len(clause.content) for clause in clauses)
    groups: list[ReviewChunk] = []
    start = 0
    for index in range(group_count):
        remaining_groups = group_count - index
        if remaining_groups == 1:
            end = len(clauses)
        else:
            target = remaining_chars / remaining_groups
            end = start + 1
            size = len(clauses[start].content)
            while end < len(clauses) - (remaining_groups - 1):
                next_size = size + len(clauses[end].content)
                if abs(next_size - target) >= abs(size - target):
                    break
                size = next_size
                end += 1
        group = clauses[start:end]
        groups.append(ReviewChunk(sequence=index + 1, clauses=group))
        remaining_chars -= sum(len(clause.content) for clause in group)
        start = end
    return groups


def split_clauses(state: ReviewState) -> dict[str, list[Clause] | list[ReviewChunk]]:
    """LangGraph 代码节点：将全文 Markdown 拆分为条款块。"""
    clauses = split_markdown_clauses(
        state["content"], state.get("document_title") or state.get("title"),
    )
    chunks = group_clauses(
        clauses,
        max_chunks=30 if state.get("review_mode") == ReviewMode.STANDARD_DOCUMENT
        else max(1, len(clauses)),
    )
    return {"clauses": clauses, "chunks": chunks}
