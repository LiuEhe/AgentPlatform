"""将 DOCX 文档转换为保留层级的 Markdown。"""

from __future__ import annotations

import re
from collections.abc import Iterator
from io import BytesIO

from docx import Document
from docx.document import Document as DocumentType
from docx.table import Table
from docx.text.paragraph import Paragraph


class DocumentReadError(ValueError):
    """文档无法读取或未包含可处理文本。"""


def _heading_level(paragraph: Paragraph) -> int | None:
    """根据 Word 段落样式读取标题级别。"""
    style_name = paragraph.style.name.strip()
    match = re.search(r"(?:heading|标题)\s*(\d+)\s*$", style_name, re.IGNORECASE)
    if match:
        return max(1, min(int(match.group(1)), 6))
    return 1 if style_name.casefold() == "title" else None


def _markdown_table(table: Table) -> str:
    """将 Word 表格转换为 Markdown 表格。"""
    rows: list[list[str]] = []
    seen_cells: set[object] = set()
    for row in table.rows:
        values = [""] * row.grid_cols_before
        for cell in row.cells:
            cell_element = cell._tc
            if cell_element in seen_cells:
                values.append("")
                continue
            seen_cells.add(cell_element)
            text = cell.text.strip().replace("\r", "").replace("\n", "<br>")
            values.append(text.replace("\\", "\\\\").replace("|", "\\|"))
        values.extend([""] * row.grid_cols_after)
        rows.append(values)
    if not rows:
        return ""

    column_count = max((len(row) for row in rows), default=0)
    if column_count == 0:
        return ""
    rows = [row + [""] * (column_count - len(row)) for row in rows]
    separator = ["---"] * column_count
    return "\n".join(
        [
            "| " + " | ".join(rows[0]) + " |",
            "| " + " | ".join(separator) + " |",
            *("| " + " | ".join(row) + " |" for row in rows[1:]),
        ]
    )


def _iter_blocks(document: DocumentType) -> Iterator[Paragraph | Table]:
    """按文档顺序遍历顶层段落和表格。"""
    yield from document.iter_inner_content()


def convert_docx_to_markdown(content: bytes) -> str:
    """读取 DOCX 字节并输出标题、段落和表格组成的 Markdown。"""
    if not content:
        raise DocumentReadError("DOCX 文件内容为空")

    try:
        document = Document(BytesIO(content))
        blocks: list[str] = []
        for block in _iter_blocks(document):
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue
                level = _heading_level(block)
                blocks.append(f"{'#' * level} {text}" if level else text)
            elif isinstance(block, Table):
                table_text = _markdown_table(block)
                if table_text:
                    blocks.append(table_text)
    except Exception as exc:
        raise DocumentReadError("DOCX 文件无法解析") from exc

    markdown = "\n\n".join(blocks).strip()
    if not markdown:
        raise DocumentReadError("DOCX 文件中没有可处理的文字或表格")
    return markdown
