"""检查制度条款之间的冲突。"""

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.institution_review.nodes._checks import create_findings_check
from app.schemas.review import ReviewCategory


def create_conflict_check(model: BaseChatModel):
    """创建条款冲突检查节点。"""
    return create_findings_check(model, ReviewCategory.CONFLICT)
