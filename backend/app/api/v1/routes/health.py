import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

log = structlog.get_logger()

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Basic liveness probe (legacy — kept for backwards compatibility)."""
    from app.core.config import settings

    return HealthResponse(status="ok", version=settings.app_version)


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Kubernetes liveness probe — is the process alive?"""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Kubernetes readiness probe — can we serve traffic?

    Checks DB (required) and Redis (optional).
    Returns 200 when all checks pass, 503 when any required dependency is degraded.
    """
    checks: dict[str, str] = {}
    overall = "ready"

    # DB check — required dependency
    try:
        await db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"
        overall = "degraded"
        log.error("health.db_check_failed", error=str(exc))

    # Redis check — optional; degraded but not fatal if unavailable
    try:
        from app.core.redis import get_redis

        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        # Redis is used for caching / sessions — degrade but don't fail hard
        if overall == "ready":
            overall = "degraded"
        log.error("health.redis_check_failed", error=str(exc))

    status_code = 200 if overall == "ready" else 503
    return JSONResponse(
        content={"status": overall, **checks},
        status_code=status_code,
    )
