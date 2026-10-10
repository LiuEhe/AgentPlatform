"""进程存活和服务就绪检查。"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import Settings

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    """报告进程是否在运行，不探测外部依赖。"""
    return {"status": "alive"}


@router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    """检查审核运行时配置是否完整。"""
    settings: Settings = request.app.state.settings
    issues = settings.readiness_issues()
    runtime_ready = getattr(request.app.state, "agent_runtime", None) is not None
    if not runtime_ready and not issues:
        issues.append("审核运行时尚未初始化")
    status = "ready" if not issues else "not_ready"
    return JSONResponse(
        status_code=200 if not issues else 503,
        content={"status": status, "issues": issues},
    )
