import asyncio
from collections import deque

import httpx
import pytest
from fastapi import FastAPI, File, UploadFile
from starlette import formparsers

from app.api import document_uploads


@pytest.mark.parametrize("path,file_count", [
    ("/custom/sessions/a/files", 1), ("/custom/reviews", 2),
])
def test_docx_limit_checks_received_bytes_and_closes_spooled_files(monkeypatch, path, file_count):
    monkeypatch.setattr(document_uploads, "MULTIPART_OVERHEAD_BYTES", 512)
    files = []
    original = formparsers.SpooledTemporaryFile

    def record_file(**options):
        temporary = original(**options)
        files.append(temporary)
        return temporary

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", record_file)
    app = FastAPI()
    seen = []

    @app.post(path)
    async def upload(file: UploadFile = File(), standard_file: UploadFile | None = File(None)):
        seen.append(True)
        return {"sizes": [len(await part.read()) for part in (file, standard_file) if part]}

    document_uploads.install_document_upload_limit(app, api_prefix="/custom", max_file_bytes=64)
    multipart_prefix = (b'--fixture\r\nContent-Disposition: form-data; name="file"; '
                        b'filename="a.docx"\r\n\r\nx')

    async def chunks():
        yield multipart_prefix
        yield b"x" * 700

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"file": ("draft.docx", b"x" * 64)}
            if file_count == 2:
                payload["standard_file"] = ("standard.docx", b"y" * 64)
            valid = await client.post(path, files=payload)
            assert valid.json() == {"sizes": [64] * file_count}
            files.clear()
            rejected = await client.post(path, content=chunks(), headers={
                "Content-Type": "multipart/form-data; boundary=fixture",
            })
            assert "content-length" not in rejected.request.headers
            assert rejected.status_code == 413
            assert rejected.json()["error"]["code"] == "UPLOAD_TOO_LARGE"
            assert rejected.json()["error"]["request_id"]
            assert len(files) == 1 and files[0].closed
            assert seen == [True]

        files.clear()
        events = deque([
            {"type": "http.request", "body": multipart_prefix, "more_body": True},
            {"type": "http.disconnect"},
        ])
        responses = []

        async def receive():
            return events.popleft()

        async def send(message):
            responses.append(message)

        await app({
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": path, "root_path": "",
            "query_string": b"", "headers": [
                (b"content-type", b"multipart/form-data; boundary=fixture"),
            ],
        }, receive, send)
        assert responses[0]["status"] == 400
        assert len(files) == 1 and files[0].closed
        assert seen == [True]

    asyncio.run(scenario())
