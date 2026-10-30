"""会话、可选材料与异步运行接口。"""

from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import ValidationError

from app.core.errors import AppError
from app.schemas.conversation import (
    TERMINAL_STATUSES,
    FileView,
    MessageCreate,
    RunEvent,
    RunView,
    SessionListView,
    SessionView,
)
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/sessions", tags=["sessions"])


def service(request: Request) -> ConversationService:
    instance = getattr(request.app.state, "conversation_service", None)
    if instance is None:
        raise AppError("SERVICE_NOT_READY", "会话服务尚未就绪", 503)
    return instance


@router.post("", status_code=201, response_model=SessionView)
async def create_conversation(request: Request) -> SessionView:
    return await service(request).create()


@router.get("/{session_id}", response_model=SessionView)
async def read_conversation(
    session_id: str,
    request: Request,
    after_sequence: int | None = Query(default=None, ge=0),
    before_sequence: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
) -> SessionView:
    if before_sequence is not None and after_sequence is not None:
        raise AppError("INVALID_CONVERSATION_INPUT", "不能同时指定前后消息位置", 422)
    return await service(request).read(
        session_id,
        after_sequence=after_sequence,
        before_sequence=before_sequence,
        limit=limit,
    )


@router.delete("/{session_id}", status_code=204, response_class=Response)
async def delete_conversation(session_id: str, request: Request) -> Response:
    await service(request).delete(session_id)
    return Response(status_code=204)


@router.get("", response_model=SessionListView)
async def list_conversations(
    request: Request,
    agent_id: str = Query(default="conversation_assistant", pattern="^conversation_assistant$"),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
) -> SessionListView:
    return await service(request).list(agent_id, limit=limit, cursor=cursor)


@router.post("/{session_id}/files", status_code=201, response_model=FileView)
async def upload_document(
    session_id: str, request: Request, file: UploadFile = File(...)
) -> FileView:
    try:
        content = await file.read(request.app.state.settings.max_upload_bytes + 1)
        return await service(request).upload(session_id, file.filename or "", content)
    finally:
        await file.close()


@router.post("/{session_id}/messages", status_code=202, response_model=RunView)
async def send_message(session_id: str, request: Request) -> RunView:
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise AppError("INVALID_CONVERSATION_INPUT", "请提交 JSON 消息", 422)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 65536:
            raise AppError("CONVERSATION_INPUT_TOO_LARGE", "消息请求超过大小限制", 413)
        body.extend(chunk)
    try:
        payload = MessageCreate.model_validate_json(bytes(body))
    except ValidationError as exc:
        raise AppError("INVALID_CONVERSATION_INPUT", "消息内容或附件引用无效", 422) from exc
    return await service(request).submit(session_id, payload)


@router.get("/{session_id}/runs/{run_id}", response_model=RunView)
async def read_run(session_id: str, run_id: str, request: Request) -> RunView:
    return await service(request).read_run(session_id, run_id)


@router.post("/{session_id}/runs/{run_id}/cancel", response_model=RunView)
async def cancel_run(session_id: str, run_id: str, request: Request) -> JSONResponse:
    instance = service(request)
    previous = await instance.read_run(session_id, run_id)
    result = await instance.cancel(session_id, run_id)
    return JSONResponse(
        status_code=200 if previous.status in TERMINAL_STATUSES else 202,
        content=result.model_dump(mode="json"),
    )


async def _run_events(session_id: str, run_id: str, request: Request) -> AsyncIterator[RunEvent]:
    # 依赖在响应头发出前运行，保留不存在时的标准 JSON 404。
    return await service(request).stream_run(session_id, run_id)


@router.get("/{session_id}/runs/{run_id}/events", response_class=EventSourceResponse)
async def stream_run(
    events: Annotated[AsyncIterator[RunEvent], Depends(_run_events)],
) -> AsyncIterator[ServerSentEvent]:
    async with aclosing(events):
        yield ServerSentEvent(retry=3000)
        async for event in events:
            yield ServerSentEvent(event=event.event, data=event)
