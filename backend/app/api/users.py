"""本人资料与管理员用户接口。"""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from app.api.auth import actor, payload
from app.schemas.identity import (
    CreateUserRequest,
    ProfileRequest,
    ResetPasswordRequest,
    StatusRequest,
)

router = APIRouter(tags=["users"])


@router.patch("/users/me")
async def profile(request: Request):
    data = await payload(request, ProfileRequest)
    return await request.app.state.user_service.update_profile(actor(request), data.display_name)


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
