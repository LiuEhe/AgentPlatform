"""完整执行结果作为单轮输出；跨轮消息另由图收尾节点更新。"""

from app.agents.conversation_assistant.schemas import AssembledReply, PreparedAction
from app.schemas.conversation_turn import ChildAgentResult


def assemble_result(
    action: PreparedAction, reply: str | None, child_call: ChildAgentResult | None
) -> AssembledReply:
    return AssembledReply(
        reply="制度审核助手已完成，结果如下。" if child_call else reply,
        child_call=child_call,
    )
