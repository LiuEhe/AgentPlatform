"""会话、可选材料与异步运行接口。"""

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.errors import AppError
from app.schemas.conversation import (
    TERMINAL_STATUSES,
    ConversationView,
    DocumentView,
    MessageCreate,
    RunView,
)
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


def service(request: Request) -> ConversationService:
    instance = getattr(request.app.state, "conversation_service", None)
    if instance is None:
        raise AppError("SERVICE_NOT_READY", "会话服务尚未就绪", 503)
    return instance


@router.post("", status_code=201, response_model=ConversationView)
async def create_conversation(request: Request) -> ConversationView:
    return await service(request).create()


@router.get("/{id}", response_model=ConversationView)
async def read_conversation(
    id: str,
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
) -> ConversationView:
    return await service(request).read(id, after_sequence=after_sequence)


@router.post("/{id}/documents", status_code=201, response_model=DocumentView)
async def upload_document(id: str, request: Request, file: UploadFile = File(...)) -> DocumentView:
    try:
        content = await file.read(request.app.state.settings.max_upload_bytes + 1)
        return await service(request).upload(id, file.filename or "", content)
    finally:
        await file.close()


@router.post("/{id}/messages", status_code=202, response_model=RunView)
async def send_message(id: str, request: Request) -> RunView:
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
    return await service(request).submit(id, payload)


@router.get("/{id}/runs/{run_id}", response_model=RunView)
async def read_run(id: str, run_id: str, request: Request) -> RunView:
    return await service(request).read_run(id, run_id)


@router.post("/{id}/runs/{run_id}/cancel", response_model=RunView)
async def cancel_run(id: str, run_id: str, request: Request) -> JSONResponse:
    instance = service(request)
    previous = await instance.read_run(id, run_id)
    result = await instance.cancel(id, run_id)
    return JSONResponse(
        status_code=200 if previous.status in TERMINAL_STATUSES else 202,
        content=result.model_dump(mode="json"),
    )
