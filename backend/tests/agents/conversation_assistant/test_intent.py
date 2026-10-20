import pytest
from pydantic import ValidationError

from app.agents.conversation_assistant.schemas import IntentDecision


@pytest.mark.parametrize("intent", ["general_chat", "institution_qa", "unsupported_task"])
def test_non_review_decision_rejects_child_call(intent):
    with pytest.raises(ValidationError):
        IntentDecision(intent=intent, action="call_agent", target_agent_id="institution_review")


@pytest.mark.parametrize("target", ["conversation_assistant", "arbitrary"])
def test_review_rejects_unknown_target(target):
    with pytest.raises(ValidationError):
        IntentDecision(intent="institution_review", action="call_agent", target_agent_id=target)


def test_ambiguous_cannot_create_pending_review():
    with pytest.raises(ValidationError):
        IntentDecision(
            intent="ambiguous", action="clarify", question="你希望做什么？", pending_action="update"
        )
