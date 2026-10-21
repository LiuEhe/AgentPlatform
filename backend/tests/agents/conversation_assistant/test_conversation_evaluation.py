def test_turning_to_chat_with_child_call_is_not_correct():
    from app.agents.conversation_assistant.evaluation import evaluate_case

    scores = evaluate_case(
        {"child_called": False, "needs_clarification": False},
        {"child_called": True, "needs_clarification": False},
    )
    assert scores[0]["value"] == 0.0


def test_missing_parameters_require_clarification():
    from app.agents.conversation_assistant.evaluation import evaluate_case

    scores = evaluate_case({"needs_clarification": True}, {"needs_clarification": False})
    assert scores[0]["value"] == 0.0
