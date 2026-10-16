import asyncio

from app.agents.institution_review.nodes.report_assemble import (
    _report_data,
    create_report_sections_node,
)
from app.agents.institution_review.schemas import Clause, ClauseReview, ClauseReviewFinding
from app.schemas.review import ReviewReference


def test_standard_report_has_source_without_findings(fake_model_factory):
    async def scenario():
        node = create_report_sections_node(fake_model_factory())
        result = await node({
            "title": "草稿", "review_mode": "standard_document", "clauses": [],
            "standard_name": "标准.docx", "standard_content": "标准全文",
        })
        assert "上传标准文档" in result["overview_markdown"]
        assert "标准.docx" in result["overview_markdown"]
        assert "未检索到" not in result["overview_markdown"]
        assert "未发现" in result["conflict_markdown"]
    asyncio.run(scenario())


def test_report_excludes_passed_clause_content_and_keeps_original_location(fake_model_factory):
    async def scenario():
        model = fake_model_factory()
        failing = ClauseReview(
            clause=Clause(sequence=2, chapter="第一章", section="第二节",
                          article="第三条", content="问题原文"),
            findings=[ClauseReviewFinding(category="conflict", description="问题",
                                          reference_indexes=[1])],
            references=[ReviewReference(document_name="标准.docx", content="相关依据")],
        )
        passed = ClauseReview(clause=Clause(sequence=1, content="通过条款唯一标记"))
        rows = _report_data([passed, failing])
        assert len(rows) == 1
        assert rows[0]["section"] == "第二节"
        assert rows[0]["sequence"] == 2
        node = create_report_sections_node(model)
        await node({
            "title": "草稿", "review_mode": "standard_document",
            "standard_name": "标准.docx", "standard_content": "标准全文唯一标记",
            "clauses": [passed.clause, failing.clause], "clause_reviews": [passed, failing],
            "references": failing.references,
        })
        for _, messages in model.calls:
            prompt = messages[-1][1]
            assert "通过条款唯一标记" not in prompt
            assert "标准全文唯一标记" not in prompt
        assert "相关依据" in model.calls[-1][1][-1][1]
    asyncio.run(scenario())


def test_kb_graph_no_references_remains_compatible(fake_model_factory):
    async def scenario():
        result = await create_report_sections_node(fake_model_factory())({"title": "草稿"})
        assert "未检索到" in result["overview_markdown"]
        assert "无法核实" in result["conflict_markdown"]
    asyncio.run(scenario())
