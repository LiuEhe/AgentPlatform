"""会话条件边由已校验动作确定。"""

from app.agents.conversation_assistant.graph.state import ConversationGraphState


def route_action(state: ConversationGraphState) -> str:
    return {
        "answer": "reply_chat",
        "clarify": "reply_clarification",
        "call_agent": "invoke_child_agent",
    }[state["prepared_action"].route]
