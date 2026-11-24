"""在 multipart 解析前限制 DOCX 请求体。"""

import re

from fastapi import FastAPI, HTTPException, Request

from app.core.errors import AppError, app_error_response

MULTIPART_OVERHEAD_BYTES = 65_536


class DocumentRequestTooLarge(HTTPException):
    def __init__(self):
        super().__init__(status_code=413)


class DocumentUploadMiddleware:
    def __init__(self, app, *, api_prefix: str, max_file_bytes: int):
        self.app = app
        self.review_path = f"{api_prefix}/reviews"
        self.session_path = re.compile(rf"{re.escape(api_prefix)}/sessions/[^/]+/files")
        self.max_file_bytes = max_file_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        path = scope["path"].rstrip("/")
        root = scope.get("root_path", "").rstrip("/")
        paths = {path, path.removeprefix(root)} if root and path.startswith(root + "/") else {path}
        if self.review_path in paths:
            limit = 2 * self.max_file_bytes + MULTIPART_OVERHEAD_BYTES
        elif any(self.session_path.fullmatch(route) for route in paths):
            limit = self.max_file_bytes + MULTIPART_OVERHEAD_BYTES
        else:
            return await self.app(scope, receive, send)

        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                raise DocumentRequestTooLarge()
            return message

        await self.app(scope, bounded_receive, send)


def install_document_upload_limit(app: FastAPI, *, api_prefix: str, max_file_bytes: int):
    app.add_middleware(
        DocumentUploadMiddleware, api_prefix=api_prefix, max_file_bytes=max_file_bytes,
    )

    @app.exception_handler(DocumentRequestTooLarge)
    async def document_request_too_large(request: Request, _exc: DocumentRequestTooLarge):
        error = AppError("UPLOAD_TOO_LARGE", "上传请求超过大小限制", 413)
        return app_error_response(request, error)
