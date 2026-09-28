"""结合检索参考检查潜在合规问题。"""

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.institution_review.nodes._checks import create_findings_check
from app.schemas.review import ReviewCategory


def create_compliance_check(model: BaseChatModel):
    """创建合规检查节点。"""
    return create_findings_check(model, ReviewCategory.COMPLIANCE)
