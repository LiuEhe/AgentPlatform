"""本人资料与管理员用户接口。"""

import asyncio
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from starlette.requests import ClientDisconnect

from app.api.auth import actor, payload
from app.core.errors import AppError
from app.schemas.identity import (
    CreateUserRequest,
    ProfileRequest,
    ResetPasswordRequest,
    StatusRequest,
)

router = APIRouter(tags=["users"])
AVATAR_MAX_BYTES = 2_097_152
AVATAR_BODY_MAX_BYTES = AVATAR_MAX_BYTES + 65_536


class AvatarParseAborted(MultiPartException):
    """让官方 multipart parser 关闭已创建的临时文件。"""


class AvatarUploadMiddleware:
    def __init__(self, app, *, api_prefix):
        self.app = app
        self.path = api_prefix + "/users/me/avatar"

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] != "POST"
                or scope["path"].rstrip("/") != self.path):
            return await self.app(scope, receive, send)
        state = scope.setdefault("state", {})
        abort = state["avatar_parse_abort"] = asyncio.Event()
        received = 0

        async def bounded_receive():
            nonlocal received
            incoming = asyncio.create_task(receive())
            cancelled = asyncio.create_task(abort.wait())
            try:
                done, _ = await asyncio.wait((incoming, cancelled),
                                             return_when=asyncio.FIRST_COMPLETED)
                if cancelled in done:
                    state["avatar_disconnected"] = True
                    raise AvatarParseAborted("Avatar request cancelled")
                message = incoming.result()
                if message["type"] == "http.disconnect":
                    state["avatar_disconnected"] = True
                    raise AvatarParseAborted("Avatar request disconnected")
                received += len(message.get("body", b""))
                if received > AVATAR_BODY_MAX_BYTES:
                    state["avatar_body_too_large"] = True
                    raise AvatarParseAborted("Avatar request too large")
                return message
            finally:
                for task in (incoming, cancelled):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(incoming, cancelled, return_exceptions=True)

        try:
            async with scope["app"].state.user_service.avatar_upload_slot():
                await self.app(scope, bounded_receive, send)
        except AppError as exc:
            response = JSONResponse(status_code=exc.status_code, content={"error": {
                "code": exc.code, "message": exc.message,
                "request_id": state.get("request_id", str(uuid4())),
            }})
            await response(scope, receive, send)


async def _avatar_form(request):
    async def parse():
        try:
            return await request.form(max_files=1, max_fields=0, max_part_size=1024)
        except HTTPException:
            if getattr(request.state, "avatar_body_too_large", False):
                raise AppError("AVATAR_TOO_LARGE", "头像请求超过大小限制", 413) from None
            if getattr(request.state, "avatar_disconnected", False):
                raise ClientDisconnect from None
            raise AppError("VALIDATION_ERROR", "请仅上传一个file头像文件", 422) from None

    task = asyncio.create_task(parse())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        request.state.avatar_parse_abort.set()
        while not task.done():
            try:
                await asyncio.shield(task)
            except (asyncio.CancelledError, Exception):
                continue
        if not task.cancelled() and task.exception() is None:
            await task.result().close()
        raise


@router.post("/users/me/avatar")
async def upload_avatar(request: Request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "multipart/form-data":
        raise AppError("VALIDATION_ERROR", "请上传multipart头像文件", 422)
    form = await _avatar_form(request)
    try:
        items = list(form.multi_items())
        if len(items) != 1 or items[0][0] != "file" or not isinstance(items[0][1], UploadFile):
            raise AppError("VALIDATION_ERROR", "请仅上传一个file头像文件", 422)
        file = items[0][1]
        content = await file.read(AVATAR_MAX_BYTES + 1)
        return await request.app.state.user_service.upload_avatar(
            actor(request), file.filename or "", content,
        )
    finally:
        await form.close()


@router.get("/users/me/avatar")
async def read_avatar(request: Request):
    return await _avatar_response(request)


@router.get("/admin/users/{user_id}/avatar")
async def read_user_avatar(user_id: UUID, request: Request):
    return await _avatar_response(request, user_id)


async def _avatar_response(request, user_id=None):
    content = await request.app.state.user_service.read_avatar(
        actor(request), target_user_id=user_id,
    )
    return Response(content, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})


@router.delete("/users/me/avatar", status_code=204)
async def remove_avatar(request: Request):
    await request.app.state.user_service.remove_avatar(actor(request))
    return Response(status_code=204)


@router.patch("/users/me")
async def profile(request: Request):
    data = await payload(request, ProfileRequest)
    return await request.app.state.user_service.update_profile(actor(request), data)


@router.get("/users/me")
async def read_profile(request: Request):
    return await request.app.state.user_service.read_profile(actor(request))


@router.get("/admin/users/{user_id}")
async def user_profile(user_id: UUID, request: Request):
    return await request.app.state.user_service.read_profile(actor(request), target_user_id=user_id)


@router.get("/admin/users")
async def list_users(request: Request, limit: int = Query(default=20, ge=1, le=100),
                     cursor: str | None = Query(default=None, max_length=512)):
    page = await request.app.state.user_service.list_users(
        actor(request), limit=limit, cursor=cursor
    )
    return {"items": page.items, "next_cursor": page.next_cursor}


@router.post("/admin/users", status_code=201)
async def create_user(request: Request):
    data = await payload(request, CreateUserRequest)
    return await request.app.state.user_service.create_user(
        actor(request), data.username, data.display_name, data.temporary_password,
    )


@router.patch("/admin/users/{user_id}")
async def status(user_id: UUID, request: Request):
    data = await payload(request, StatusRequest)
    return await request.app.state.user_service.set_status(actor(request), user_id, data.status)


@router.post("/admin/users/{user_id}/password-reset", status_code=204)
async def reset_password(user_id: UUID, request: Request):
    data = await payload(request, ResetPasswordRequest)
    await request.app.state.user_service.reset_password(
        actor(request), user_id, data.temporary_password,
    )
    return Response(status_code=204)
