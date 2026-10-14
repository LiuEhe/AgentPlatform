from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _client() -> TestClient:
    settings = Settings(
        _env_file=None,
        llm_model=None,
        llm_api_key=None,
        ragflow_base_url=None,
        ragflow_api_key=None,
        ragflow_dataset_id=None,
    )
    return TestClient(create_app(settings))


def test_get_agent_graph_returns_complete_topology() -> None:
    expected_nodes = [
        {"id": "START", "label": "开始"},
        {"id": "split_clauses", "label": "条款拆分"},
        {"id": "review_clauses", "label": "条款审查"},
        {"id": "check_terminology", "label": "术语检查"},
        {"id": "generate_report_sections", "label": "生成报告内容"},
        {"id": "generate_suggestions", "label": "生成修改建议"},
        {"id": "assemble_report", "label": "组装报告"},
        {"id": "END", "label": "结束"},
    ]
    expected_edges = [
        {"sources": ["START"], "target": "split_clauses"},
        {"sources": ["START"], "target": "check_terminology"},
        {"sources": ["split_clauses"], "target": "review_clauses"},
        {
            "sources": ["review_clauses", "check_terminology"],
            "target": "generate_report_sections",
        },
        {
            "sources": ["generate_report_sections"],
            "target": "generate_suggestions",
        },
        {"sources": ["generate_suggestions"], "target": "assemble_report"},
        {"sources": ["assemble_report"], "target": "END"},
    ]

    with _client() as client:
        response = client.get("/api/v1/agents/institution_review/graph")

    assert response.status_code == 200
    assert response.json() == {
        "agent_id": "institution_review",
        "name": "制度审核助手",
        "nodes": expected_nodes,
        "edges": expected_edges,
    }


def test_get_agent_graph_does_not_require_agent_runtime() -> None:
    with _client() as client:
        assert client.app.state.agent_runtime is None

        response = client.get("/api/v1/agents/institution_review/graph")

    assert response.status_code == 200
    assert response.json()["agent_id"] == "institution_review"


def test_get_agent_graph_unknown_id_returns_standard_404() -> None:
    with _client() as client:
        response = client.get("/api/v1/agents/not_registered/graph")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "AGENT_GRAPH_NOT_FOUND"
    assert error["message"] == "未找到该智能体的流程图"
    assert error["request_id"]
