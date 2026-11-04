"""只在动作门控通过后取完整材料调用子智能体。"""

from app.agents.conversation_assistant.schemas import PreparedReview
from app.agents.conversation_assistant.tools.institution_review import invoke_review
from app.runtime.agent_runtime import AgentInvoker
from app.schemas.conversation_turn import ChildAgentResult, MaterialReader


async def invoke_child_agent(
    invoke_agent: AgentInvoker, prepared: PreparedReview, read_materials: MaterialReader,
) -> ChildAgentResult:
    return await invoke_review(invoke_agent, prepared, read_materials)
