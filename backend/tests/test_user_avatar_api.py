import asyncio
from io import BytesIO

import pytest
from fastapi import FastAPI
from PIL import Image
from starlette import formparsers
from starlette.requests import ClientDisconnect
from test_user_profile_api import profile_client

from app.api.users import AvatarUploadMiddleware, router
from app.core.errors import install_error_handlers
from app.infrastructure.identity.avatar_store import AvatarStore
from app.services.user_service import UserService


def png():
    output = BytesIO()
    Image.new("RGB", (4, 4), "red").save(output, "PNG")
    return output.getvalue()


def test_avatar_routes_require_bound_identity(tmp_path):
    client, f = profile_client(AvatarStore(tmp_path))
    with client:
        assert client.get("/api/v1/users/me/avatar").status_code == 404
        assert client.get("/api/v1/users/me/avatar",
                          headers={"X-Auth-Session-ID": "old"}).status_code == 409
        assert client.get(f"/api/v1/admin/users/{f.other}/avatar").status_code == 403
        response = client.post("/api/v1/users/me/avatar", files={"file": ("a.png", png())})
        assert response.status_code == 200 and response.json()["has_avatar"]
        assert "avatar_path" not in response.json()
        image = client.get("/api/v1/users/me/avatar")
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
        assert image.headers["content-type"] == "image/png"
        assert image.headers["cache-control"] == "no-store"
        assert image.headers["x-content-type-options"] == "nosniff"
        f.rows[f.actor.user.user_id]["role"] = "admin"
        assert client.get(f"/api/v1/admin/users/{f.actor.user.user_id}/avatar").status_code == 200
        for _ in range(2):
            assert client.delete("/api/v1/users/me/avatar").status_code == 204
        assert client.get("/api/v1/users/me/avatar").status_code == 404


def test_multipart_rejects_extra_fields_and_closes_files(tmp_path):
    client, _ = profile_client(AvatarStore(tmp_path))
    with client:
        assert client.post("/api/v1/users/me/avatar", files={"file": ("a.png", png())},
                           data={"unexpected": "x"}).status_code == 422
        assert client.post("/api/v1/users/me/avatar", files=[("file", ("a.png", png())),
                           ("file", ("b.png", png()))]).status_code == 422
        assert client.post("/api/v1/users/me/avatar", files={"wrong": ("a.png", png())}
                           ).status_code == 422
        assert not list(tmp_path.rglob("*.png"))
        assert client.post("/api/v1/users/me/avatar", files={"file": ("a.svg", b"<svg/>")}
                           ).status_code == 415
        assert client.post("/api/v1/users/me/avatar", files={"file": ("a.png", b"bad")}
                           ).status_code == 422
        assert client.post("/api/v1/users/me/avatar", files={"file": ("a.png", b"x" * 2097153)}
                           ).status_code == 413


def test_chunked_multipart_body_is_bounded_without_content_length(tmp_path):
    client, _ = profile_client(AvatarStore(tmp_path))
    with client:
        def chunks():
            yield (b'--boundary\r\nContent-Disposition: form-data; '
                   b'name="file"; filename="a.png"\r\n\r\n')
            for _ in range(35):
                yield b"x" * 65536
            yield b"\r\n--boundary--\r\n"
        for headers in ({}, {"Content-Length": "1"}):
            response = client.post("/api/v1/users/me/avatar", content=chunks(), headers={
                **headers, "Content-Type": "multipart/form-data; boundary=boundary",
            })
            assert response.status_code == 413
            assert response.json()["error"]["code"] == "AVATAR_TOO_LARGE"
        assert not list(tmp_path.rglob("*.png"))


@pytest.mark.parametrize("mode", ["cancel", "disconnect", "duplicate", "too-large"])
def test_raw_asgi_failures_close_spooled_files_and_release_slots(tmp_path, monkeypatch, mode):
    async def scenario():
        files = []
        created = asyncio.Event()
        original_factory = formparsers.SpooledTemporaryFile

        def record_file(*args, **kwargs):
            file = original_factory(*args, **kwargs)
            files.append(file)  # Retain references so GC cannot conceal a missing close.
            created.set()
            return file

        monkeypatch.setattr(formparsers, "SpooledTemporaryFile", record_file)
        service = UserService(None, None, AvatarStore(tmp_path))
        app = FastAPI()
        app.state.user_service = service
        app.add_middleware(AvatarUploadMiddleware, api_prefix="/api/v1")
        app.include_router(router, prefix="/api/v1")
        install_error_handlers(app)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/api/v1/users/me/avatar",
                 "root_path": "", "query_string": b"", "server": ("testserver", 80),
                 "client": ("127.0.0.1", 1), "headers": [
                     (b"content-type", b"multipart/form-data; boundary=b"),
                 ]}
        prefix = (b'--b\r\nContent-Disposition: form-data; name="file"; '
                  b'filename="a.png"\r\n\r\npartial')
        calls = 0
        responses = []

        async def receive():
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"type": "http.request", "body": prefix, "more_body": True}
            if mode == "cancel":
                await asyncio.Event().wait()
            if mode == "disconnect":
                return {"type": "http.disconnect"}
            body = b"x" * 2_162_688 if mode == "too-large" else (
                b'\r\n--b\r\nContent-Disposition: form-data; name="file"; '
                b'filename="b.png"\r\n\r\nsecond\r\n--b--\r\n'
            )
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            responses.append(message)

        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(created.wait(), 2)
            if mode == "cancel":
                await asyncio.sleep(0)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 2)
            elif mode == "disconnect":
                with pytest.raises(ClientDisconnect):
                    await task
            else:
                await task
                status = next(item["status"] for item in responses
                              if item["type"] == "http.response.start")
                assert status == (413 if mode == "too-large" else 422)
            assert calls >= 2
            assert files and all(file.closed for file in files)
            assert service._avatar_slots._value == 2
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await service.aclose()
    asyncio.run(scenario())
