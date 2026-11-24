"""进程存活和服务就绪检查。"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import Settings
from app.core.errors import AppError

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    """报告进程是否在运行，不探测外部依赖。"""
    return {"status": "alive"}


@router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    """检查审核运行时和业务数据库是否可用。"""
    settings: Settings = request.app.state.settings
    issues = settings.readiness_issues()
    runtime_ready = getattr(request.app.state, "agent_runtime", None) is not None
    if not runtime_ready and not issues:
        issues.append("审核运行时尚未初始化")
    database = getattr(request.app.state, "database", None)
    if database is None:
        issues.append("数据库暂时不可用")
    else:
        try:
            await database.probe()
        except (AppError, TimeoutError):
            issues.append("数据库暂时不可用")
    status = "ready" if not issues else "not_ready"
    model_issues = settings.model_issues()
    kb_issues = model_issues + settings.ragflow_issues()
    return JSONResponse(
        status_code=200 if not issues else 503,
        content={
            "status": status, "issues": issues,
            "modes": {
                "standard_document": {"configured": not model_issues, "issues": model_issues},
                "knowledge_base": {"configured": not kb_issues, "issues": kb_issues},
            },
        },
    )
