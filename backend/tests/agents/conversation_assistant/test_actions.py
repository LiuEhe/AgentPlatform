import pytest
from pydantic import ValidationError

from app.agents.conversation_assistant.config import ConversationAgentConfig
from app.agents.conversation_assistant.nodes.action_prepare import prepare_action
from app.agents.conversation_assistant.nodes.material_prepare import prepare_materials
from app.agents.conversation_assistant.schemas import IntentDecision
from app.schemas.conversation_turn import ContinuationState, TurnDocument

CONFIG = ConversationAgentConfig(True, 50000)
DRAFT = {"kind": "document", "id": "draft"}
STANDARD = {"kind": "document", "id": "standard"}


@pytest.fixture
def review_turn(turn_factory):
    return turn_factory(
        documents=(
            TurnDocument(id="draft", filename="同名.docx", markdown="# 草稿\n第一条 草稿  原文"),
            TurnDocument(id="standard", filename="同名.docx", markdown="# 标准\n第一条 标准"),
        )
    )


def decision(**updates):
    return IntentDecision.model_validate(
        {
            "intent": "institution_review",
            "action": "call_agent",
            "target_agent_id": "institution_review",
            **updates,
        }
    )


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"draft": DRAFT},
        {"draft": DRAFT, "review_mode": "standard_document"},
        {"draft": DRAFT, "standard": DRAFT, "review_mode": "standard_document"},
    ],
)
def test_missing_or_conflicting_review_parameters_clarify(review_turn, args):
    action = prepare_action(
        review_turn,
        decision(review_args=args),
        prepare_materials(review_turn),
        CONFIG,
    )
    assert action.route == "clarify" and action.review is None and action.continuation


def test_complete_review_maps_exact_uploaded_content(review_turn):
    action = prepare_action(
        review_turn,
        decision(
            review_args={
                "draft": DRAFT,
                "standard": STANDARD,
                "review_mode": "standard_document",
            }
        ),
        prepare_materials(review_turn),
        CONFIG,
    )
    assert action.route == "call_agent"
    assert action.review.payload["content"] == review_turn.documents[0].markdown
    assert action.review.payload["standard_content"] == review_turn.documents[1].markdown


def test_pasted_text_review_requires_no_upload(review_turn):
    action = prepare_action(
        review_turn,
        decision(
            review_args={
                "draft": {"kind": "user_message", "id": "m1"},
                "standard": STANDARD,
                "review_mode": "standard_document",
            }
        ),
        prepare_materials(review_turn),
        CONFIG,
    )
    assert action.review.payload["content"] == "你好"


def test_followup_keeps_draft_and_switch_clears_standard(review_turn):
    review_turn.continuation = ContinuationState(
        payload={
            "arguments": {
                "draft": DRAFT,
                "standard": STANDARD,
                "review_mode": "standard_document",
            }
        }
    )
    action = prepare_action(
        review_turn,
        decision(
            pending_action="update",
            review_args={"review_mode": "knowledge_base"},
        ),
        prepare_materials(review_turn),
        CONFIG,
    )
    assert action.route == "call_agent"
    assert action.review.payload["content"] == review_turn.documents[0].markdown
    assert "standard_content" not in action.review.payload


def test_new_task_does_not_inherit_previous_draft(review_turn):
    review_turn.continuation = ContinuationState(payload={"arguments": {"draft": DRAFT}})
    action = prepare_action(
        review_turn,
        decision(
            pending_action="clear",
            review_args={"review_mode": "knowledge_base"},
        ),
        prepare_materials(review_turn),
        CONFIG,
    )
    assert action.route == "clarify"
    assert action.continuation.payload["arguments"]["draft"] is None


@pytest.mark.parametrize("intent,action", [("general_chat", "answer"), ("ambiguous", "clarify")])
def test_non_review_clears_pending(review_turn, intent, action):
    review_turn.continuation = ContinuationState(payload={"arguments": {"draft": DRAFT}})
    value = IntentDecision(
        intent=intent, action=action, question="请说明" if action == "clarify" else None
    )
    result = prepare_action(review_turn, value, prepare_materials(review_turn), CONFIG)
    assert result.continuation is None and result.review is None


def test_unconfigured_knowledge_base_clears_pending(review_turn):
    action = prepare_action(
        review_turn,
        decision(
            review_args={
                "draft": DRAFT,
                "review_mode": "knowledge_base",
            }
        ),
        prepare_materials(review_turn),
        ConversationAgentConfig(False, 50000),
    )
    assert action.route == "clarify" and action.continuation is None


@pytest.mark.parametrize("target", ["conversation_assistant", "unknown"])
def test_invalid_model_constructed_target_is_revalidated(review_turn, target):
    value = IntentDecision.model_construct(
        intent="institution_review",
        action="call_agent",
        target_agent_id=target,
        pending_action="clear",
        review_args=None,
        question=None,
    )
    with pytest.raises(ValidationError):
        prepare_action(review_turn, value, prepare_materials(review_turn), CONFIG)
