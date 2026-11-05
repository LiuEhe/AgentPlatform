from dataclasses import replace
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_user_profile_store import make_store

from app.api.auth import install_auth_guard
from app.api.auth import router as auth_router
from app.api.users import AvatarUploadMiddleware, router
from app.core.config import Settings
from app.core.errors import AppError, install_error_handlers
from app.infrastructure.identity.postgres_store import _identity
from app.services.user_service import UserService


def profile_client(avatars=None):
    f = make_store()
    app = FastAPI()
    app.state.settings = Settings(_env_file=None)

    async def authenticate(cookie):
        row = f.rows[f.actor.user.user_id]
        if cookie != "valid" or row["status"] != "active":
            raise AppError("AUTH_REQUIRED", "请登录", 401)
        return replace(f.actor, user=_identity(row))

    app.state.auth_service = SimpleNamespace(authenticate=authenticate)
    service = UserService(f.store, None, avatars)
    app.state.user_service = service
    app.add_middleware(AvatarUploadMiddleware, api_prefix="/api/v1")
    install_auth_guard(app)
    install_error_handlers(app)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    client.cookies.set("agent-platform-session-dev", "valid")
    client.headers.update({"Origin": "http://localhost:5173",
                           "X-Auth-Session-ID": str(f.actor.auth_session_id),
                           "X-CSRF-Token": "csrf"})
    return client, f


def test_profile_http_clearing_and_privilege_rejection():
    client, f = profile_client()
    with client:
        response = client.patch("/api/v1/users/me", json={"bio": "new", "email": None})
        assert response.status_code == 200
        assert response.json()["email"] is None and response.json()["bio"] == "new"
        assert client.get("/api/v1/users/me").json()["bio"] == "new"
        for value in ({"role": "admin"}, {"avatar_path": "../file"}, {"display_name": None}):
            assert client.patch("/api/v1/users/me", json=value).status_code == 422
        assert client.patch("/api/v1/users/me", json={}).status_code == 200
        summary = client.get("/api/v1/auth/me").json()["user"]
        assert "email" not in summary and "bio" not in summary and "avatar_path" not in summary
        assert client.get(f"/api/v1/admin/users/{f.other}").status_code == 403
        f.rows[f.actor.user.user_id]["role"] = "admin"
        assert client.get(f"/api/v1/admin/users/{f.other}").json()["status"] == "disabled"
        assert client.get(f"/api/v1/admin/users/{f.actor.user.user_id}").status_code == 200


def test_profile_http_reuses_guards_and_registration_contract():
    client, f = profile_client()
    with client:
        assert client.patch("/api/v1/users/me", json={"bio": "x"},
                            headers={"X-CSRF-Token": "bad"}).status_code == 403
        stale = client.get("/api/v1/users/me", headers={"X-Auth-Session-ID": "old"})
        assert stale.status_code == 409
        assert client.patch("/api/v1/users/me", json={"bio": "x"},
                            headers={"Origin": "https://invalid.example"}).status_code == 403
        assert client.post("/api/v1/auth/register", json={"username": "new", "display_name": "New",
                           "password": "test-pass123", "email": "a@example.com"}).status_code == 422
        f.rows[f.actor.user.user_id]["must_change_password"] = True
        assert client.get("/api/v1/users/me").status_code == 403
        f.rows[f.actor.user.user_id]["must_change_password"] = False
        f.rows[f.actor.user.user_id]["status"] = "disabled"
        assert client.get("/api/v1/users/me").status_code == 401
