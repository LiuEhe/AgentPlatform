from fastapi.testclient import TestClient
from test_observability_runtime import RecordingObserver

from app.core.config import Settings
from app.main import create_app


def test_poll_and_health_do_not_create_remote_traces(monkeypatch):
    observer = RecordingObserver()
    monkeypatch.setattr("app.main.create_observer", lambda _: observer)
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/api/v1/sessions/missing").status_code == 404
        assert observer.records == []
        result = client.post("/api/v1/sessions")
        assert result.status_code == 201
        assert result.headers["X-Request-ID"]
        assert len(observer.records) == 1
