"""检查制度文本中的重复条款。"""

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.institution_review.nodes._checks import create_findings_check
from app.schemas.review import ReviewCategory


def create_duplicate_check(model: BaseChatModel):
    """创建重复条款检查节点。"""
    return create_findings_check(model, ReviewCategory.DUPLICATE)
