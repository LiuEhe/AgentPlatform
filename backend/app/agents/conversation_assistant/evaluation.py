"""会话策略的离线评价投影；不改变业务响应。"""


def project_evaluation(state):
    action = state["prepared_action"]
    return {
        "action": action.route,
        "child_called": state.get("child_call") is not None,
        "needs_clarification": action.route == "clarify",
    }


def evaluate_case(expected, actual):
    return [
        {
            "name": key,
            "value": float(actual.get(key) == value),
            "comment": "matched" if actual.get(key) == value else "mismatch",
        }
        for key, value in expected.items()
    ]
