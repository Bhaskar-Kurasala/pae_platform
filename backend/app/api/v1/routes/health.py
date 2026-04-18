"""Health endpoints.

- `/health` — legacy combined check, kept for existing consumers.
- `/health/live` — liveness: is the process up at all? (K8s `livenessProbe`)
- `/health/ready` — readiness: can we actually serve traffic? (K8s
  `readinessProbe`) — checks DB and Redis. Returns 503 on any failure so
  load balancers and orchestrators route around the instance.

P3 3B #160.
"""

from typing import Literal

import structlog
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

log = structlog.get_logger()

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class ReadinessCheck(BaseModel):
    ok: bool
    error: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, ReadinessCheck]


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """Basic liveness probe (legacy — kept for backwards compatibility)."""
    from app.core.config import settings

    return HealthResponse(status="ok", version=settings.app_version)


@router.get("/health/live", response_model=LivenessResponse, tags=["health"])
async def liveness() -> LivenessResponse:
    """Cheap process-up check — no external dependencies."""
    return LivenessResponse(status="ok")


async def _check_db() -> ReadinessCheck:
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return ReadinessCheck(ok=True)
    except Exception as exc:  # noqa: BLE001
        return ReadinessCheck(ok=False, error=str(exc)[:200])


async def _check_redis() -> ReadinessCheck:
    from app.core.redis import get_redis

    try:
        client = await get_redis()
        pong = await client.ping()
        return ReadinessCheck(ok=bool(pong))
    except Exception as exc:  # noqa: BLE001
        return ReadinessCheck(ok=False, error=str(exc)[:200])


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    tags=["health"],
    responses={503: {"model": ReadinessResponse}},
)
async def readiness(response: Response) -> ReadinessResponse:
    """Dependency check — DB and Redis must both respond."""
    from app.core.config import settings

    db_check, redis_check = await _check_db(), await _check_redis()
    checks = {"db": db_check, "redis": redis_check}
    all_ok = all(c.ok for c in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        failed = [name for name, c in checks.items() if not c.ok]
        log.warning("health.ready.degraded", failed=failed)
    return ReadinessResponse(
        status="ok" if all_ok else "degraded",
        version=settings.app_version,
        checks=checks,
    )
