import pytest
from pydantic import ValidationError

from app.agents.institution_review.adapter import InstitutionReviewInput
from app.agents.institution_review.schemas import ReviewMode
from app.core.config import Settings


def test_default_and_env_concurrency(monkeypatch):
    monkeypatch.delenv("INSTITUTION_REVIEW_CONCURRENCY", raising=False)
    assert Settings(_env_file=None).institution_review_concurrency == 3
    monkeypatch.setenv("INSTITUTION_REVIEW_CONCURRENCY", "2")
    assert Settings(_env_file=None).institution_review_concurrency == 2


@pytest.mark.parametrize("value", [0, -1, "not-an-integer"])
def test_invalid_concurrency(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, institution_review_concurrency=value)


def test_legacy_input_defaults_to_knowledge_base():
    value = InstitutionReviewInput(title="草稿", content="第一条 正文")
    assert value.review_mode == ReviewMode.KNOWLEDGE_BASE
    assert value.standard_content is None


def test_standard_input_keeps_document_roles():
    value = InstitutionReviewInput(
        title="草稿", content="草稿正文", review_mode="standard_document",
        standard_name="标准.docx", standard_content="标准正文",
    )
    assert value.content == "草稿正文"
    assert value.standard_content == "标准正文"


@pytest.mark.parametrize("extra", [
    {"review_mode": "unknown"},
    {"review_mode": "standard_document"},
    {"review_mode": "standard_document", "standard_name": "标准", "standard_content": " "},
    {"standard_name": "标准", "standard_content": "标准正文"},
])
def test_review_input_rejects_invalid_mode_contract(extra):
    with pytest.raises(ValidationError):
        InstitutionReviewInput(title="草稿", content="第一条 正文", **extra)
