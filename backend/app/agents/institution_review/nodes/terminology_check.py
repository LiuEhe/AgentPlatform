"""检查制度文本中的术语一致性。"""

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.institution_review.nodes._checks import create_findings_check
from app.schemas.review import ReviewCategory


def create_terminology_check(model: BaseChatModel):
    """创建术语检查节点。"""
    return create_findings_check(model, ReviewCategory.TERMINOLOGY)
