import asyncio

import pytest

from app.agents.conversation_assistant.schemas import PreparedReview, ReviewArguments
from app.agents.conversation_assistant.tools.institution_review import invoke_review
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentExecution
from app.schemas.conversation_turn import MaterialReference, TurnMaterial

REF = MaterialReference(kind="user_message", id="draft")


async def reader(refs):
    assert refs == (REF,)
    return (TurnMaterial(ref=REF, title="粘贴正文", content="原文"),)


def prepared():
    return PreparedReview(arguments=ReviewArguments(draft=REF, review_mode="knowledge_base"))


def test_child_markdown_is_not_rewritten():
    calls = []
    async def invoke(agent_id, payload):
        calls.append((agent_id, payload))
        return AgentExecution("invocation", agent_id, "# 真实报告\n\n原文  保持")
    result = asyncio.run(invoke_review(invoke, prepared(), reader))
    assert result.output == "# 真实报告\n\n原文  保持" and result.invocation_id == "invocation"
    assert calls[0][0] == "institution_review" and calls[0][1]["content"] == "原文"


@pytest.mark.parametrize(
    "output,code",
    [
        (" ", "AGENT_OUTPUT_INVALID"),
        ("x" * 200001, "AGENT_OUTPUT_TOO_LARGE"),
        ({}, "AGENT_OUTPUT_INVALID"),
    ],
    ids=["blank", "too-large", "wrong-type"],
)
def test_invalid_child_output_fails(output, code):
    async def invoke(agent_id, payload):
        return AgentExecution("i", agent_id, output)
    with pytest.raises(AppError) as raised:
        asyncio.run(invoke_review(invoke, prepared(), reader))
    assert raised.value.code == code
