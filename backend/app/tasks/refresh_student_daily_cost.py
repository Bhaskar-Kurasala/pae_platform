"""D9 / Pass 3f §D.1 — refresh `mv_student_daily_cost` materialized view.

Celery beat schedule: every 60 seconds. Pass 3f §D.1 calls the
60-second cadence intentional — at 1k students × 50 INR/day max,
the worst-case 60-second drift is ~5% over-grant, which is
acceptable for a soft cap.

Uses CONCURRENTLY so the refresh doesn't lock writes on agent_actions.
This requires a unique index on the matview (created in migration
0057), without which CONCURRENTLY raises an error.

Idempotent: running multiple refreshes in quick succession just
re-aggregates the same data. The Celery beat schedule is the only
caller in production; manual triggers via celery CLI are safe for
debugging.
"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import text

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal

log = structlog.get_logger()


async def _run() -> dict[str, str]:
    async with AsyncSessionLocal() as session:
        # CONCURRENTLY does NOT lock the view for reads; readers see
        # the old snapshot until the new one is ready. The unique index
        # `idx_mv_sdc_user_day` (created in migration 0057) is the
        # prerequisite — without it, this command raises:
        #   "CONCURRENTLY ... requires UNIQUE INDEX"
        await session.execute(
            text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_student_daily_cost")
        )
        await session.commit()
    return {"status": "ok"}


@celery_app.task(name="app.tasks.refresh_student_daily_cost.refresh")
def refresh_student_daily_cost_task() -> dict[str, str]:
    """Beat-driven matview refresh.

    Errors are logged but not re-raised — a transient Postgres hiccup
    shouldn't trip the Celery worker. The next 60-second tick will
    retry; meanwhile reads see the prior snapshot, which means a
    student's cost ceiling check uses up-to-60s-stale data. Better
    than a hard failure that takes the whole cost-tracking pipeline
    offline.
    """
    try:
        result = asyncio.run(_run())
        log.debug("refresh_student_daily_cost.complete", **result)
        return result
    except Exception as exc:  # noqa: BLE001 — task never raises, beat continues
        log.warning(
            "refresh_student_daily_cost.failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return {"status": "error", "error": str(exc)}
