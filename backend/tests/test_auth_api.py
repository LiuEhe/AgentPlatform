import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.infrastructure.database import Database
from app.main import create_app

AUTH_TEST = True
ORIGIN = {"Origin": "http://localhost:5173"}
PASSWORD = "test-pass123"


@pytest.fixture
def auth_client(postgres_target, tmp_path, monkeypatch):
    import app.main as main

    dsn, schema = postgres_target
    settings = Settings(_env_file=None, database_url=dsn, documents_dir=tmp_path)
    monkeypatch.setattr(main, "Database", lambda *a, **kw: Database(
        settings, schema=schema, on_unavailable=kw.get("on_unavailable"),
    ))
    with TestClient(create_app(settings)) as client:
        yield client


def login(client, username="admin", password=PASSWORD):
    result = client.post("/api/v1/auth/login", json={
        "username": username, "password": password,
    }, headers=ORIGIN)
    assert result.status_code == 200, result.text
    context = result.json()
    client.headers.update({**ORIGIN, "X-Auth-Session-ID": context["auth_session_id"],
                           "X-CSRF-Token": context["csrf_token"]})
    return context


def test_open_registration_login_and_server_side_logout(auth_client):
    client = auth_client
    response = client.post("/api/v1/auth/register", json={
        "username": "  Alice  ", "display_name": "Alice", "password": PASSWORD,
    }, headers=ORIGIN)
    assert response.status_code == 201, response.text
    assert response.json()["username"] == "alice"
    assert response.json()["role"] == "user"
    assert not response.json()["must_change_password"]
    assert "set-cookie" not in response.headers
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client, "alice")
    assert client.get("/api/v1/auth/me").json()["user"]["username"] == "alice"
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204 and "set-cookie" not in response.headers
    assert client.get("/api/v1/auth/me").status_code == 401


def test_auth_errors_keep_cors_headers_for_the_trusted_frontend(auth_client):
    client = auth_client
    response = client.get('/api/v1/sessions', headers=ORIGIN)
    assert response.status_code == 401
    assert response.headers.get('access-control-allow-origin') == ORIGIN['Origin']
    assert response.headers.get('access-control-allow-credentials') == 'true'
    login(client)
    response = client.patch('/api/v1/users/me', json={'display_name': 'new'},
                            headers={'X-CSRF-Token': 'wrong'})
    assert response.status_code == 403
    assert response.headers.get('access-control-allow-origin') == ORIGIN['Origin']


def test_registration_does_not_replace_existing_login_and_rejects_privilege_fields(auth_client):
    client = auth_client
    original = login(client)
    for extra in ({"role": "admin"}, {"user_id": str(uuid.uuid4())}, {"status": "active"}):
        response = client.post("/api/v1/auth/register", json={
            "username": "alice", "display_name": "Alice", "password": PASSWORD, **extra,
        })
        assert response.status_code == 422
    assert client.post("/api/v1/auth/register", json={
        "username": "alice", "display_name": "Alice", "password": PASSWORD,
    }).status_code == 201
    assert client.get("/api/v1/auth/me").json()["auth_session_id"] == original["auth_session_id"]


def test_origin_csrf_context_and_admin_are_verified(auth_client):
    client = auth_client
    assert client.post("/api/v1/auth/register", json={
        "username": "alice", "display_name": "Alice", "password": PASSWORD,
    }).status_code == 403
    login(client)
    assert client.patch("/api/v1/users/me", json={"display_name": "new"}, headers={
        "X-CSRF-Token": "wrong",
    }).status_code == 403
    assert client.patch("/api/v1/users/me", json={"display_name": "new"}, headers={
        "X-Auth-Session-ID": str(uuid.uuid4()),
    }).status_code == 409
    assert client.post("/api/v1/admin/users", json={
        "username": "alice", "display_name": "Alice", "temporary_password": PASSWORD,
    }).status_code == 201
    login(client, "alice")
    assert client.get("/api/v1/admin/users").status_code == 403
    result = client.post("/api/v1/auth/password", json={
        "current_password": PASSWORD, "new_password": PASSWORD + "-changed",
    })
    assert result.status_code == 204 and "set-cookie" not in result.headers
    assert client.get("/api/v1/auth/me").status_code == 401


def test_sessions_and_cursors_are_owned_by_the_authenticated_user(auth_client):
    client = auth_client
    login(client)
    session = client.post("/api/v1/sessions")
    assert session.status_code == 201, session.text
    sid = session.json()["session_id"]
    assert client.post('/api/v1/sessions').status_code == 201
    cursor = client.get('/api/v1/sessions?limit=1').json()['next_cursor']
    assert cursor
    for name in ("alice", "bob"):
        assert client.post("/api/v1/auth/register", json={
            "username": name, "display_name": name, "password": PASSWORD,
        }).status_code == 201
    login(client, "alice")
    assert client.get("/api/v1/sessions").json()["items"] == []
    assert client.get('/api/v1/sessions', params={'cursor': cursor}).status_code == 422
    for method, path, kwargs in (
        ("get", f"/sessions/{sid}", {}),
        ("delete", f"/sessions/{sid}", {}),
        ("get", f"/sessions/{sid}/runs/{uuid.uuid4()}", {}),
        (
            "post",
            f"/sessions/{sid}/messages",
            {"json": {"client_message_id": "foreign", "content": "hi"}},
        ),
    ):
        result = getattr(client, method)("/api/v1" + path, **kwargs)
        assert result.status_code == 404, result.text
    own = client.post("/api/v1/sessions")
    assert own.status_code == 201
    login(client, "bob")
    assert client.get("/api/v1/sessions").json()["items"] == []
    assert client.get("/api/v1/sessions/" + own.json()["session_id"]).status_code == 404


def test_replaced_cookie_rejects_old_context_before_any_business_write(auth_client):
    client = auth_client
    old = login(client)
    assert client.post('/api/v1/auth/register', json={
        'username': 'alice', 'display_name': 'Alice', 'password': PASSWORD,
    }).status_code == 201
    current = login(client, 'alice')
    response = client.post('/api/v1/sessions', headers={
        'X-Auth-Session-ID': old['auth_session_id'], 'X-CSRF-Token': old['csrf_token'],
    })
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "AUTH_CONTEXT_CHANGED"
    )
    assert client.get('/api/v1/sessions').json()['items'] == []
    assert client.get('/api/v1/auth/me').json()['auth_session_id'] == current['auth_session_id']


def test_anonymous_business_matrix_and_cookie_attributes(auth_client):
    client = auth_client
    for method, path in [('get', '/agents/institution_review/graph'), ('get', '/sessions'),
                         ('post', '/reviews'), ('post', '/documents/export/docx')]:
        response = getattr(client, method)('/api/v1' + path, headers=ORIGIN)
        assert response.status_code == 401
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}, headers=ORIGIN
    )
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie and 'path=/' in cookie
    assert 'max-age' not in cookie and 'secure' not in cookie


def test_foreign_orphan_cleanup_remains_private(auth_client, monkeypatch):
    client = auth_client
    admin = login(client)
    sid = client.post("/api/v1/sessions").json()["session_id"]
    files = client.app.state.conversation_service._files
    paths = files.publish(
        files.stage("conversation_assistant", sid, str(uuid.uuid4()), b"source", "body")
    )
    original = files.discard_session
    def unavailable(*args):
        raise OSError("controlled cleanup failure")
    monkeypatch.setattr(files, "discard_session", unavailable)
    assert client.delete(f"/api/v1/sessions/{sid}").status_code == 503
    assert files.read_deletion_intent(sid).user_id == admin["user"]["user_id"]
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"username": "alice", "display_name": "Alice", "password": PASSWORD},
        ).status_code
        == 201
    )
    login(client, "alice")
    assert client.delete(f"/api/v1/sessions/{sid}").status_code == 404
    assert (files.root / paths.source_path).exists()
    monkeypatch.setattr(files, "discard_session", original)
    login(client)
    assert client.delete(f"/api/v1/sessions/{sid}").status_code == 204
    assert not (files.root / paths.source_path).exists()


def test_admin_reset_disable_and_builtin_protection(auth_client):
    client = auth_client
    admin = login(client)
    user = client.post(
        "/api/v1/admin/users",
        json={"username": "alice", "display_name": "Alice", "temporary_password": PASSWORD},
    ).json()
    assert (
        client.patch(
            "/api/v1/admin/users/" + admin["user"]["user_id"], json={"status": "disabled"}
        ).status_code
        == 409
    )
    context = login(client, "alice")
    assert client.post('/api/v1/sessions').status_code == 403
    assert client.get('/api/v1/agents/institution_review/graph').status_code == 403
    assert client.post('/api/v1/documents/export/docx', json={"markdown": "x"}).status_code == 403
    assert client.post('/api/v1/reviews').status_code == 403
    login(client)
    assert (
        client.patch(
            "/api/v1/admin/users/" + user["user_id"], json={"status": "disabled"}
        ).status_code
        == 200
    )
    result = client.post('/api/v1/auth/login', json={"username": "alice", "password": PASSWORD})
    assert result.status_code == 401 and 'set-cookie' not in result.headers
    assert (
        client.patch(
            "/api/v1/admin/users/" + user["user_id"], json={"status": "active"}
        ).status_code
        == 200
    )
    result = client.post(
        "/api/v1/admin/users/" + user["user_id"] + "/password-reset",
        json={"temporary_password": PASSWORD + "-new"},
    )
    assert result.status_code == 204 and 'set-cookie' not in result.headers
    assert client.get('/api/v1/auth/me').headers['cache-control'] == 'no-store'
    assert context['auth_session_id'] != admin['auth_session_id']


def test_registration_limit_and_bounded_body(auth_client, monkeypatch):
    client = auth_client
    # Rejected input never reaches expensive hashing; allowed attempts have their own IP bucket.
    assert (
        client.post(
            "/api/v1/auth/register",
            content="x" * 16385,
            headers={**ORIGIN, "Content-Type": "application/json"},
        ).status_code
        == 413
    )

    async def fast_hash(password):
        return 'test-hash-only'
    monkeypatch.setattr(client.app.state.auth_service.passwords, 'hash', fast_hash)
    for i in range(10):
        assert (
            client.post(
                "/api/v1/auth/register",
                json={"username": f"user{i}", "display_name": "User", "password": PASSWORD},
                headers=ORIGIN,
            ).status_code
            == 201
        )
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "blocked", "display_name": "User", "password": PASSWORD},
        headers=ORIGIN,
    )
    assert response.status_code == 429 and int(response.headers['retry-after']) > 0
