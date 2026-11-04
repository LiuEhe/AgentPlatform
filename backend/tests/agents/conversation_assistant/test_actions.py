import pytest
from pydantic import ValidationError

from app.agents.conversation_assistant.config import ConversationAgentConfig
from app.agents.conversation_assistant.nodes.action_prepare import prepare_action
from app.agents.conversation_assistant.nodes.material_prepare import prepare_materials
from app.agents.conversation_assistant.schemas import IntentDecision, PendingReview, ReviewArguments
from app.schemas.conversation_turn import MaterialReference, TurnDocument

CONFIG = ConversationAgentConfig(True, 50000)
DRAFT = {"kind": "document", "id": "draft"}
STANDARD = {"kind": "document", "id": "standard"}


@pytest.fixture
def review_turn(turn_factory):
    return turn_factory(documents=(
        TurnDocument(id="draft", filename="同名.docx", markdown="# 草稿\n第一条 草稿  原文"),
        TurnDocument(id="standard", filename="同名.docx", markdown="# 标准\n第一条 标准"),
    ))


def decision(**updates):
    return IntentDecision.model_validate({
        "intent": "institution_review", "action": "call_agent",
        "target_agent_id": "institution_review", **updates,
    })


def act(turn, value, pending=None, config=CONFIG):
    return prepare_action(value, pending, prepare_materials([], turn), config,
                          question_message_id=turn.assistant_message_id)


@pytest.mark.parametrize("args", [
    {}, {"draft": DRAFT}, {"draft": DRAFT, "review_mode": "standard_document"},
    {"draft": DRAFT, "standard": DRAFT, "review_mode": "standard_document"},
])
def test_missing_or_conflicting_review_parameters_clarify(review_turn, args):
    action = act(review_turn, decision(review_args=args))
    assert action.route == "clarify" and action.review is None and action.pending_review
    assert action.pending_review.question_message_id == review_turn.assistant_message_id


def test_complete_review_preserves_exact_material_references(review_turn):
    action = act(review_turn, decision(review_args={
        "draft": DRAFT, "standard": STANDARD, "review_mode": "standard_document",
    }))
    assert action.route == "call_agent"
    assert action.review.arguments.draft == MaterialReference(**DRAFT)
    assert action.review.arguments.standard == MaterialReference(**STANDARD)
    assert not hasattr(action.review, "payload")


def test_pasted_text_review_requires_no_upload(review_turn):
    action = act(review_turn, decision(review_args={
        "draft": {"kind": "user_message", "id": "m1"}, "standard": STANDARD,
        "review_mode": "standard_document",
    }))
    assert action.review.arguments.draft.id == review_turn.message.id


def test_followup_keeps_draft_and_switch_clears_standard(review_turn):
    pending = PendingReview(arguments=ReviewArguments(
        draft=DRAFT, standard=STANDARD, review_mode="standard_document",
    ), question_message_id="previous")
    action = act(review_turn, decision(pending_action="update", review_args={
        "review_mode": "knowledge_base",
    }), pending)
    assert action.route == "call_agent"
    assert action.review.arguments.draft == MaterialReference(**DRAFT)
    assert action.review.arguments.standard is None


def test_new_task_does_not_inherit_previous_draft(review_turn):
    pending = PendingReview(arguments=ReviewArguments(draft=DRAFT), question_message_id="previous")
    action = act(review_turn, decision(pending_action="clear", review_args={
        "review_mode": "knowledge_base",
    }), pending)
    assert action.route == "clarify" and action.pending_review.arguments.draft is None


@pytest.mark.parametrize("intent,action", [("general_chat", "answer"), ("ambiguous", "clarify")])
def test_non_review_clears_pending(review_turn, intent, action):
    pending = PendingReview(arguments=ReviewArguments(draft=DRAFT), question_message_id="previous")
    result = act(review_turn, IntentDecision(
        intent=intent, action=action, question="请说明" if action == "clarify" else None,
    ), pending)
    assert result.pending_review is None and result.review is None


def test_unconfigured_knowledge_base_clears_pending(review_turn):
    action = act(
        review_turn,
        decision(review_args={"draft": DRAFT, "review_mode": "knowledge_base"}),
        config=ConversationAgentConfig(False, 50000),
    )
    assert action.route == "clarify" and action.pending_review is None


@pytest.mark.parametrize("target", ["conversation_assistant", "unknown"])
def test_invalid_model_constructed_target_is_revalidated(review_turn, target):
    value = IntentDecision.model_construct(
        intent="institution_review", action="call_agent", target_agent_id=target,
        pending_action="clear", review_args=None, question=None,
    )
    with pytest.raises(ValidationError):
        act(review_turn, value)
