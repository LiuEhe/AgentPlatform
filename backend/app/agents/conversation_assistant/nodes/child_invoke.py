"""执行已通过门控的单次审核子调用。"""

from app.agents.conversation_assistant.schemas import PreparedReview
from app.agents.conversation_assistant.tools.institution_review import invoke_review
from app.runtime.agent_runtime import AgentInvoker
from app.schemas.conversation_turn import ChildAgentResult


async def invoke_child_agent(
    invoke_agent: AgentInvoker,
    prepared: PreparedReview,
) -> ChildAgentResult:
    return await invoke_review(invoke_agent, prepared)
