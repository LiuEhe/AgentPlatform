import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.schemas.conversation import MessageCreate


def settings(**updates):
    return Settings(_env_file=None, llm_model="test", llm_api_key="test", **updates)


def test_create_and_chat_without_multipart(monkeypatch, fake_model_factory):
    async def handler(schema, messages):
        return {"intent": "general_chat", "action": "answer"} if schema else "你好，随时可以聊。"

    monkeypatch.setattr("app.main.create_llm_service", lambda _: fake_model_factory(handler))
    with TestClient(create_app(settings())) as client:
        created = client.post("/api/v1/conversations")
        assert created.status_code == 201
        id = created.json()["id"]
        sent = client.post(
            f"/api/v1/conversations/{id}/messages",
            json={"client_message_id": "m1", "content": "你好"},
        )
        assert sent.status_code == 202
        run_id = sent.json()["id"]
        for _ in range(100):
            run = client.get(f"/api/v1/conversations/{id}/runs/{run_id}").json()
            if run["status"] in {"succeeded", "failed"}:
                break
        assert run["status"] == "succeeded"
        assert run["message"]["agent_call"] is None
        assert run["message"]["content"] == "你好，随时可以聊。"


def test_no_model_allows_session_but_not_execution():
    with TestClient(
        create_app(Settings(_env_file=None, llm_model=None, llm_api_key=None))
    ) as client:
        id = client.post("/api/v1/conversations").json()["id"]
        response = client.post(
            f"/api/v1/conversations/{id}/messages",
            json={"client_message_id": "m1", "content": "你好"},
        )
        assert response.status_code == 503
        assert client.get("/api/v1/conversations/missing").status_code == 404


def test_upload_and_input_boundaries(docx_bytes_factory):
    with TestClient(
        create_app(Settings(_env_file=None, llm_model=None, llm_api_key=None))
    ) as client:
        id = client.post("/api/v1/conversations").json()["id"]
        response = client.post(
            f"/api/v1/conversations/{id}/documents",
            files={"file": ("草稿.docx", docx_bytes_factory())},
        )
        assert response.status_code == 201
        assert response.json()["filename"] == "草稿.docx" and response.json()["chars"] > 0
        assert client.get(f"/api/v1/conversations/{id}").json()["messages"] == []
        assert (
            client.post(
                f"/api/v1/conversations/{id}/documents", files={"file": ("x.doc", b"bad")}
            ).status_code
            == 415
        )
        assert (
            client.post(f"/api/v1/conversations/{id}/messages", json={"content": " "}).status_code
            == 422
        )


def test_message_accepts_no_documents():
    assert MessageCreate(client_message_id="m1", content="你好").document_ids == []


@pytest.mark.parametrize("updates", [{"content": "  "}, {"extra": True}, {"content": "x" * 12001}])
def test_invalid_message_is_rejected(updates):
    with pytest.raises(ValidationError):
        MessageCreate.model_validate({"client_message_id": "m1", "content": "你好"} | updates)


@pytest.mark.parametrize(
    "filename,content,code",
    [
        ("x.doc", b"x", "UNSUPPORTED_DOCUMENT_TYPE"),
        ("x.docx", b"broken", "INVALID_DOCX"),
        ("x.docx", b"", "EMPTY_DOCUMENT"),
    ],
)
def test_invalid_uploaded_document_rejected(filename, content, code):
    with TestClient(
        create_app(Settings(_env_file=None, llm_model=None, llm_api_key=None))
    ) as client:
        id = client.post("/api/v1/conversations").json()["id"]
        response = client.post(
            f"/api/v1/conversations/{id}/documents", files={"file": (filename, content)}
        )
        assert response.status_code in {415, 422}
        assert response.json()["error"]["code"] == code
