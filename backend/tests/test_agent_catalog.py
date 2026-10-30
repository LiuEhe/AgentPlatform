from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_agents_are_database_metadata_without_model_configuration():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/api/v1/agents")
        assert response.status_code == 200
        assert {a["agent_id"] for a in response.json()} == {
            "conversation_assistant", "institution_review",
        }
        store = client.app.state.conversation_service._store

        async def change():
            async with store._connection(write=True) as conn:
                await conn.execute(
                    "UPDATE agents SET name='数据库名称' WHERE agent_id='conversation_assistant'"
                )

        client.portal.call(change)
        assert client.get("/api/v1/agents").json()[0]["name"] == "数据库名称"
        assert client.app.state.agent_runtime is None


def test_new_session_contract_has_no_old_alias_or_trusted_client_user():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.post("/api/v1/sessions")
        assert response.status_code == 201
        view = response.json()
        assert "session_id" in view and "id" not in view
        assert "files" in view and "documents" not in view
        assert client.get("/api/v1/conversations").status_code == 404
        assert client.post(
            f"/api/v1/sessions/{view['session_id']}/messages",
            json={"client_message_id": "x", "content": "你好", "user_id": "someone"},
        ).status_code == 422
