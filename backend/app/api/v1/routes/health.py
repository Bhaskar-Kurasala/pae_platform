"""Health endpoints.

- `/health` — legacy combined check, kept for existing consumers.
- `/health/live` — liveness: is the process up at all? (K8s `livenessProbe`)
- `/health/ready` — readiness: can we actually serve traffic? (K8s
  `readinessProbe`) — checks DB, Redis, and Anthropic key presence.
  Returns 503 on any hard failure so load balancers and orchestrators
  route around the instance.
- `/health/version` — the SHA / build-time / env triple, set during the
  Docker build so on-call can verify which build is in front of the user
  (PR3/C6.2).

PR2/B5.2 introduced statement_timeout, PR2/B4.1 introduced the global
exception handler. PR3/C6 finalizes the K8s/Fly probe contract:

  * `/health/live` is the *liveness* probe — never reports anything
    external, so a flapping dep can't get the instance restarted.
  * `/health/ready` is the *readiness* probe — when any required
    dep is down, returns 503 + a structured detail so an orchestrator
    can route traffic away. Anthropic is reported as `"skipped"` when
    no key is configured (dev / CI), `"ok"` when configured. We
    intentionally do NOT make a live HTTP call to Anthropic — its
    rate-limit budget is precious and its uptime isn't ours to gate on.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
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
    """Per-dep verdict.

    `ok=True` for green, `ok=False` for unreachable, `ok=True` with
    `status="skipped"` for deps we intentionally don't probe (e.g.
    Anthropic, when no key is configured).
    """

    ok: bool
    status: Literal["ok", "unreachable", "skipped"] = "ok"
    error: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, ReadinessCheck]


class VersionResponse(BaseModel):
    """Build provenance for the running container.

    Populated at Docker build time via three build args
    (`BUILD_COMMIT_SHA`, `BUILD_TIME`) which the Dockerfile sets as
    `ENV` so the running process can read them. `env` reflects the
    runtime `ENVIRONMENT` setting from `app.core.config.Settings`.
    """

    commit_sha: str
    build_time: str
    env: str


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
        return ReadinessCheck(ok=True, status="ok")
    except Exception as exc:  # noqa: BLE001
        return ReadinessCheck(
            ok=False, status="unreachable", error=str(exc)[:200]
        )


async def _check_redis() -> ReadinessCheck:
    from app.core.redis import get_redis

    try:
        client = await get_redis()
        pong = await client.ping()
        if not bool(pong):
            return ReadinessCheck(
                ok=False, status="unreachable", error="ping returned falsy"
            )
        return ReadinessCheck(ok=True, status="ok")
    except Exception as exc:  # noqa: BLE001
        return ReadinessCheck(
            ok=False, status="unreachable", error=str(exc)[:200]
        )


async def _check_anthropic() -> ReadinessCheck:
    """Report key presence only.

    We deliberately do NOT make a live HTTP call here — that would burn
    the project's rate-limit budget on every probe (Fly + K8s probe
    every ~10s) and tie our readiness to a third-party uptime we can't
    control. Skipped = dev/CI without a key; ok = key configured.
    """
    from app.core.config import settings

    if not settings.anthropic_api_key:
        return ReadinessCheck(ok=True, status="skipped")
    return ReadinessCheck(ok=True, status="ok")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    tags=["health"],
    responses={503: {"model": ReadinessResponse}},
)
async def readiness(response: Response) -> ReadinessResponse:
    """Dependency check — DB and Redis must both respond. Anthropic
    key presence is reported but not load-bearing.

    Returns 503 with a structured detail listing the failed deps when
    any required dep is unreachable. Anthropic is informational only:
    a missing key in dev returns `"skipped"` and never trips 503.
    """
    from app.core.config import settings

    db_check, redis_check, anthropic_check = (
        await _check_db(),
        await _check_redis(),
        await _check_anthropic(),
    )
    checks = {
        "db": db_check,
        "redis": redis_check,
        "anthropic": anthropic_check,
    }
    # Anthropic is informational; readiness gates only on db + redis.
    required_checks = {"db": db_check, "redis": redis_check}
    all_ok = all(c.ok for c in required_checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        failed = [name for name, c in required_checks.items() if not c.ok]
        log.warning(
            "health.ready.degraded",
            failed=failed,
            errors={
                name: c.error
                for name, c in required_checks.items()
                if not c.ok and c.error
            },
        )
    return ReadinessResponse(
        status="ok" if all_ok else "degraded",
        version=settings.app_version,
        checks=checks,
    )


@router.get(
    "/health/version",
    response_model=VersionResponse,
    tags=["health"],
)
async def version() -> VersionResponse:
    """Return the build provenance triple.

    `BUILD_COMMIT_SHA` and `BUILD_TIME` are stamped into the image at
    Docker build time. On a local dev run without a build, both fall
    back to sentinel values so on-call can tell at a glance ("dev"
    means the binary wasn't built through CI). `env` is the runtime
    setting — it can differ from build env (e.g. a prod-built image
    deployed to staging).
    """
    from app.core.config import settings

    return VersionResponse(
        commit_sha=os.environ.get("BUILD_COMMIT_SHA", "dev"),
        build_time=os.environ.get(
            "BUILD_TIME", datetime.now(UTC).isoformat()
        ),
        env=settings.environment,
    )
