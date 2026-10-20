"""语义意图识别，结构化输出仍须经过确定性门控。"""

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.conversation_assistant.prompts import INTENT_PROMPT
from app.agents.conversation_assistant.schemas import ConversationInput, IntentDecision
from app.core.errors import AppError


async def classify_intent(model: BaseChatModel, payload: ConversationInput) -> IntentDecision:
    try:
        value = await model.with_structured_output(IntentDecision).ainvoke(
            [
                ("system", INTENT_PROMPT),
                ("human", payload.model_dump_json()),
            ]
        )
        return IntentDecision.model_validate(value)
    except Exception as exc:
        raise AppError(
            "CONVERSATION_INTENT_FAILED",
            "暂时无法理解请求，请换个说法重试",
            502,
        ) from exc
