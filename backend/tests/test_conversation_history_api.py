from datetime import UTC, datetime

from app.schemas.conversation import SessionListView, SessionSummaryView, SessionView


def test_persistent_history_contract_has_pagination_not_expiry():
    now = datetime.now(UTC)
    summary = SessionSummaryView(
        session_id="c",
        agent_id="conversation_assistant",
        title="历史",
        created_at=now,
        updated_at=now,
    )
    view = SessionView(
        **summary.model_dump(),
        messages=[],
        files=[],
        active_run_id=None,
        last_sequence=100,
        has_more=True,
        next_after_sequence=50,
    )
    assert view.next_after_sequence == 50
    assert "expires_in_seconds" not in view.model_dump()
    assert SessionListView(items=[summary], next_cursor=None).items[0].title == "历史"
