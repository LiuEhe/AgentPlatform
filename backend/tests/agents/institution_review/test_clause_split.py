import pytest

from app.agents.institution_review.nodes.clause_split import (
    group_clauses,
    split_clauses,
    split_markdown_clauses,
)
from app.agents.institution_review.schemas import Clause


@pytest.mark.parametrize("count", [1, 30, 31, 60, 100])
def test_grouping_preserves_order_and_content(count):
    clauses = [Clause(sequence=i, content="等长正文") for i in range(1, count + 1)]
    groups = group_clauses(clauses)
    assert len(groups) == min(30, count)
    assert all(group.clauses for group in groups)
    assert [c for group in groups for c in group.clauses] == clauses
    if count == 60:
        assert [len(group.clauses) for group in groups] == [2] * 30


def test_uneven_grouping_preserves_locations_and_single_long_clause():
    clauses = [
        Clause(sequence=i, content="文" * (20_000 if i == 16 else i),
               chapter="第一章", section="第二节", article=f"第{i}条")
        for i in range(1, 72)
    ]
    groups = group_clauses(clauses)
    assert len(groups) == 30
    assert [c.model_dump() for g in groups for c in g.clauses] == [
        c.model_dump() for c in clauses
    ]
    assert group_clauses([clauses[15]])[0].clauses[0].content == "文" * 20_000


def test_empty_grouping_and_invalid_limit():
    assert group_clauses([]) == []
    with pytest.raises(ValueError):
        group_clauses([], max_chunks=0)


def test_split_keeps_original_clauses_but_only_caps_standard_batches():
    content = "\n".join(f"第{i}条 正文" for i in range(1, 61))
    kb = split_clauses({"title": "草稿", "content": content})
    standard = split_clauses({
        "title": "草稿", "content": content, "review_mode": "standard_document",
    })
    assert len(kb["chunks"]) == 60
    assert len(standard["chunks"]) == 30
    assert kb["clauses"] == standard["clauses"]


def test_title_only_yields_no_clauses():
    assert split_markdown_clauses("# 草稿", "草稿") == []


def test_split_preserves_chapter_section_article_paragraph_item():
    clauses = split_markdown_clauses(
        "# 草稿\n第一章 总则\n第二节 范围\n第三条 要求\n（一）范围\n1. 具体要求", "草稿",
    )
    clause = clauses[-1]
    assert (clause.chapter, clause.section, clause.article, clause.paragraph, clause.item) == (
        "第一章 总则", "第二节 范围", "第三条 要求", "（一）", "1.",
    )
    assert "具体要求" in clause.content
