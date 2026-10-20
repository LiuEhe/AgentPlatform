"""普通对话回复与确定性澄清；不具有子智能体调用能力。"""

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.conversation_assistant.prompts import CHAT_PROMPT
from app.agents.conversation_assistant.schemas import ConversationInput, PreparedAction
from app.core.errors import AppError


async def generate_reply(model: BaseChatModel, payload: ConversationInput) -> str:
    try:
        result = await model.ainvoke(
            [
                ("system", CHAT_PROMPT),
                ("human", payload.model_dump_json()),
            ]
        )
        content = getattr(result, "content", result)
        if isinstance(content, list):
            content = "\n".join(
                part["text"]
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        if not isinstance(content, str) or not content.strip() or len(content) > 200000:
            raise ValueError("Invalid conversation reply")
        return content
    except Exception as exc:
        raise AppError("MODEL_ERROR", "会话回答失败，请稍后重试", 502) from exc


def clarification_reply(action: PreparedAction) -> str:
    if not (action.question or "").strip():
        raise AppError("INVALID_AGENT_ACTION", "澄清内容无效", 502)
    return action.question
