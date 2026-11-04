"""会话 Agent 所需的只读能力配置。"""

from dataclasses import dataclass

from app.nodes.llm.memory import MemoryPolicy


@dataclass(frozen=True)
class ConversationAgentConfig:
    knowledge_base_configured: bool
    max_review_chars: int
    memory_policy: MemoryPolicy = MemoryPolicy()


MAX_CONTEXT_CHARS = 24000
AGENT_RESULT_EXCERPT_CHARS = 4000
