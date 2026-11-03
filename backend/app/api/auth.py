"""认证HTTP、浏览器来源与会话上下文保护。"""

import asyncio
import hmac
from contextlib import aclosing
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.core.errors import AppError, request_id_for
from app.schemas.identity import LoginRequest, PasswordRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


def cookie_name(settings):
    return "agent-platform-session-dev" if settings.app_env == "development" else (
        "__Host-agent-platform-session"
    )


def check_origin(request):
    origin = request.headers.get("origin")
    if origin is None:
        parsed = urlsplit(request.headers.get("referer", ""))
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    if origin not in request.app.state.settings.auth_trusted_origins:
        raise AppError("CSRF_REJECTED", "请求来源无效，请从平台页面重试", 403)


def check_context(request, actor, *, stream=False):
    expected = request.query_params.get("auth_session_id") if stream else (
        request.headers.get("x-auth-session-id")
    )
    if expected != str(actor.auth_session_id):
        raise AppError("AUTH_CONTEXT_CHANGED", "登录状态已改变，请重新确认登录", 409)


def check_csrf(request, actor):
    supplied = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(supplied.encode(), actor.csrf_token.encode()):
        raise AppError("CSRF_REJECTED", "请求校验失败，请重新打开页面", 403)


def actor(request):
    return request.state.actor


async def payload(request, model):
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise AppError("VALIDATION_ERROR", "请提交JSON数据", 422)
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > 16384:
            raise AppError("AUTH_REQUEST_TOO_LARGE", "账号请求超过大小限制", 413)
        body.extend(part)
    try:
        return model.model_validate_json(body)
    except ValidationError:
        raise AppError("VALIDATION_ERROR", "账号信息格式无效，请检查填写内容", 422) from None


def auth_view(context):
    return {"user": context.user, "auth_session_id": str(context.auth_session_id),
            "csrf_token": context.csrf_token, "expires_at": context.expires_at}


def source_ip(request):
    return request.client.host if request.client else "unknown"


@router.post("/register", status_code=201)
async def register(request: Request):
    data = await payload(request, RegisterRequest)
    return await request.app.state.auth_service.register(
        data.username, data.display_name, data.password, source_ip=source_ip(request),
    )


@router.post("/login")
async def login(request: Request, response: Response):
    data = await payload(request, LoginRequest)
    settings = request.app.state.settings
    grant = await request.app.state.auth_service.login(
        data.username, data.password, source_ip=source_ip(request),
        old_token=request.cookies.get(cookie_name(settings)),
    )
    response.set_cookie(cookie_name(settings), grant.cookie_token, httponly=True,
                        secure=settings.app_env != "development", samesite="lax", path="/")
    return auth_view(grant.context)


@router.get("/me")
async def me(request: Request):
    return auth_view(actor(request))


@router.post("/logout", status_code=204)
async def logout(request: Request):
    current = getattr(request.state, "actor", None)
    if current is not None:
        await request.app.state.auth_service.logout(current)
    return Response(status_code=204)


@router.post("/password", status_code=204)
async def change_password(request: Request):
    data = await payload(request, PasswordRequest)
    await request.app.state.auth_service.change_password(
        actor(request), data.current_password, data.new_password,
    )
    return Response(status_code=204)


def install_auth_guard(app):
    @app.middleware("http")
    async def protect(request, call_next):
        prefix = request.app.state.settings.api_prefix
        path = request.url.path.rstrip("/")
        if not path.startswith(prefix + "/") or request.method == "OPTIONS":
            return await call_next(request)
        try:
            write = request.method not in {"GET", "HEAD", "OPTIONS"}
            if write:
                check_origin(request)
            public = {prefix + "/agents", prefix + "/auth/register", prefix + "/auth/login"}
            if path not in public:
                service = request.app.state.auth_service
                try:
                    current = await service.authenticate(request.cookies.get(
                        cookie_name(request.app.state.settings),
                    ))
                except AppError as exc:
                    if path != prefix + "/auth/logout" or exc.code != "AUTH_REQUIRED":
                        raise
                    current = None
                request.state.actor = current
                if current is not None:
                    if path != prefix + "/auth/me":
                        check_context(request, current, stream=path.endswith("/events"))
                        if write:
                            check_csrf(request, current)
                    if current.user.must_change_password and path not in {
                        prefix + "/auth/me", prefix + "/auth/password", prefix + "/auth/logout",
                    }:
                        raise AppError("PASSWORD_CHANGE_REQUIRED", "请先修改临时密码", 403)
                    if path.startswith(prefix + "/admin/") and current.user.role != "admin":
                        raise AppError("FORBIDDEN", "没有管理用户的权限", 403)
                    session_prefix = prefix + "/sessions/"
                    if path.startswith(session_prefix):
                        session_id = path[len(session_prefix):].split("/", 1)[0]
                        await request.app.state.conversation_service.authorize(
                            current, session_id, optional=request.method == "DELETE",
                        )
            response = await call_next(request)
        except AppError as exc:
            response = JSONResponse(status_code=exc.status_code, content={"error": {
                "code": exc.code, "message": exc.message, "request_id": request_id_for(request),
            }})
            if exc.retry_after_seconds is not None:
                response.headers["Retry-After"] = str(exc.retry_after_seconds)
        response.headers["Cache-Control"] = "no-store"
        vary = response.headers.get("Vary", "")
        response.headers["Vary"] = vary + ", Cookie" if vary else "Cookie"
        return response


async def guard_run_events(context, events, *, assert_live):
    pending = None
    async with aclosing(events):
        try:
            while True:
                await assert_live(context)
                if pending is None:
                    pending = asyncio.create_task(anext(events))
                remaining = (context.expires_at - datetime.now(UTC)).total_seconds()
                if remaining <= 0:
                    return
                done, _ = await asyncio.wait({pending}, timeout=min(5, remaining))
                if not done:
                    continue
                try:
                    event = pending.result()
                except StopAsyncIteration:
                    return
                pending = None
                await assert_live(context)
                yield event
        except AppError:
            return
        finally:
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
