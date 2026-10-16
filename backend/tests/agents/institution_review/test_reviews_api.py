from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def settings(**updates):
    values = dict(
        _env_file=None, llm_model="test-model", llm_api_key="test-key",
        ragflow_base_url=None, ragflow_api_key=None, ragflow_dataset_id=None,
        institution_review_concurrency=2,
    )
    return Settings(**(values | updates))


def test_standard_request_without_rag_runs_real_graph(
    monkeypatch, fake_model_factory, docx_bytes_factory,
):
    model = fake_model_factory()
    monkeypatch.setattr("app.main.create_llm_service", lambda _: model)
    with TestClient(create_app(settings())) as client:
        response = client.post("/api/v1/reviews", data={"review_mode": "standard_document"}, files={
            "file": ("同名.docx", docx_bytes_factory(body="第一条 草稿正文")),
            "standard_file": ("同名.docx", docx_bytes_factory(title="标准", body="标准全文")),
        })
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        for title in ("一. 简述", "二. 冲突检测", "三. 术语检测", "四. 修改建议"):
            assert title in response.text
        assert "上传标准文档" in response.text
        assert "同名.docx" in response.text
        prompt = next(messages[-1][1] for schema, messages in model.calls
                      if schema and schema.__name__ == "StandardReviewOutput")
        assert "第一条 草稿正文" in prompt and "标准全文" in prompt


def test_readiness_reports_mode_configuration_without_probing(monkeypatch, fake_model_factory):
    monkeypatch.setattr("app.main.create_llm_service", lambda _: fake_model_factory())
    with TestClient(create_app(settings())) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready" and data["issues"] == []
        assert data["modes"]["standard_document"]["configured"] is True
        assert data["modes"]["knowledge_base"]["configured"] is False


def test_missing_model_keeps_runtime_unready():
    with TestClient(create_app(settings(llm_model=None, llm_api_key=None))) as client:
        assert client.app.state.agent_runtime is None
        assert client.get("/health/ready").status_code == 503


def test_kb_request_without_rag_returns_503(monkeypatch, fake_model_factory, docx_bytes_factory):
    model = fake_model_factory()
    monkeypatch.setattr("app.main.create_llm_service", lambda _: model)
    with TestClient(create_app(settings())) as client:
        response = client.post("/api/v1/reviews", files={
            "file": ("草稿.docx", docx_bytes_factory()),
        })
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RAGFLOW_NOT_CONFIGURED"
    assert model.calls == []


@pytest.mark.parametrize("mode,with_standard", [
    ("standard_document", False), ("knowledge_base", True), ("unknown", False),
])
def test_contradictory_form_rejected_before_model(
    mode, with_standard, monkeypatch, fake_model_factory, docx_bytes_factory,
):
    model = fake_model_factory()
    monkeypatch.setattr("app.main.create_llm_service", lambda _: model)
    files = {"file": ("草稿.docx", docx_bytes_factory())}
    if with_standard:
        files["standard_file"] = ("标准.docx", docx_bytes_factory())
    with TestClient(create_app(settings())) as client:
        response = client.post("/api/v1/reviews", data={"review_mode": mode}, files=files)
    assert response.status_code == 422
    assert model.calls == []


def test_draft_only_legacy_request_works(monkeypatch, fake_model_factory, docx_bytes_factory):
    async def retrieve(*args, **kwargs):
        return []
    monkeypatch.setattr("app.main.create_llm_service", lambda _: fake_model_factory())
    monkeypatch.setattr("app.main.RagFlowClient", lambda *_: SimpleNamespace(retrieve=retrieve))
    with TestClient(create_app(settings(
        ragflow_base_url="http://ragflow.test", ragflow_api_key="test", ragflow_dataset_id="test",
    ))) as client:
        response = client.post("/api/v1/reviews", files={
            "file": ("草稿.docx", docx_bytes_factory()),
        })
    assert response.status_code == 200
    assert "知识库" in response.text


def test_review_failure_returns_error_without_partial_report(
    monkeypatch, fake_model_factory, docx_bytes_factory,
):
    async def failure(schema, messages):
        raise RuntimeError("test model quota exhausted")
    monkeypatch.setattr("app.main.create_llm_service", lambda _: fake_model_factory(failure))
    with TestClient(create_app(settings())) as client:
        response = client.post("/api/v1/reviews", data={"review_mode": "standard_document"}, files={
            "file": ("草稿.docx", docx_bytes_factory()),
            "standard_file": ("标准.docx", docx_bytes_factory()),
        })
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_ERROR"
    assert "test model quota" not in response.text


def test_invalid_standard_rejected_before_model(
    monkeypatch, fake_model_factory, docx_bytes_factory,
):
    model = fake_model_factory()
    monkeypatch.setattr("app.main.create_llm_service", lambda _: model)
    with TestClient(create_app(settings())) as client:
        response = client.post("/api/v1/reviews", data={"review_mode": "standard_document"}, files={
            "file": ("草稿.docx", docx_bytes_factory()),
            "standard_file": ("标准.docx", b"broken"),
        })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_DOCX"
    assert model.calls == []


@pytest.mark.parametrize("title", ["草稿", "内部  制度", "超长标题" * 60])
def test_title_only_draft_rejected_without_model_calls(
    title, monkeypatch, fake_model_factory, docx_bytes_factory,
):
    async def forbidden(schema, messages):
        raise RuntimeError("无正文不应调用模型")
    model = fake_model_factory(forbidden)
    monkeypatch.setattr("app.main.create_llm_service", lambda _: model)
    with TestClient(create_app(settings())) as client:
        response = client.post("/api/v1/reviews", data={"review_mode": "standard_document"}, files={
            "file": ("草稿.docx", docx_bytes_factory(title=title, body="")),
            "standard_file": ("标准.docx", docx_bytes_factory()),
        })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REVIEW_CONTENT_EMPTY"
    assert model.calls == []
