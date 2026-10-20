"""会话 Agent 所需的只读能力配置。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationAgentConfig:
    knowledge_base_configured: bool
    max_review_chars: int
