"""Liveness and readiness.

Kept apart on purpose: liveness answers "is this process alive" and must never
depend on a downstream, or a database blip restarts healthy containers.
Readiness answers "can this process serve traffic" and does check dependencies.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.api.deps import SessionDep, SettingsDep
from app.core.logging import get_logger
from app.schemas.common import HealthResponse

log = get_logger(__name__)

router = APIRouter(tags=["health"])

VERSION = "0.1.0"


@router.get("/live", response_model=HealthResponse)
async def liveness(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(status="ok", version=VERSION, environment=settings.app_env)


@router.get("/ready", response_model=HealthResponse)
async def readiness(
    request: Request, session: SessionDep, settings: SettingsDep, response: Response
) -> HealthResponse:
    checks: dict[str, str] = {}

    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"

    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {type(exc).__name__}"
    else:
        checks["redis"] = "not configured"

    sandbox = getattr(request.app.state, "sandbox", None)
    if sandbox is not None:
        checks["sandbox"] = "ok" if await sandbox.available() else "unavailable"
    else:
        checks["sandbox"] = "disabled"

    checks["llm"] = "ok" if request.app.state.registry.all_models() else "no provider configured"
    checks["embeddings"] = request.app.state.embeddings.name

    # Only the database makes this instance unable to serve. A missing sandbox
    # degrades analysis but leaves upload and Q&A working, so it must not pull
    # the instance out of the load balancer.
    ready = checks["database"] == "ok"
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if ready else "degraded",
        version=VERSION,
        environment=settings.app_env,
        checks=checks,
    )
