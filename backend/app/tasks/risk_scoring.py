"""F1 — Nightly risk-scoring Celery task.

Runs once per day (Beat schedule: 03:00 UTC, off-peak for Neon). Calls
the F1 student_risk_service to recompute every active user's slip
pattern + risk score. Output lands in the student_risk_signals table
(F0/0049 migration); F4 admin console panels read from there.

The task is idempotent — re-running it overwrites yesterday's signals
via ON CONFLICT (user_id) so nothing accumulates.
"""

from __future__ import annotations

import asyncio

import structlog

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.services.student_risk_service import score_all_users

log = structlog.get_logger()


async def _run() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        scored = await score_all_users(session)
    return {"scored": scored}


@celery_app.task(name="app.tasks.risk_scoring.score_all_users")
def score_all_users_task() -> dict[str, int]:
    """Entry point invoked by Celery Beat at 03:00 UTC daily."""
    log.info("risk_scoring.task_start")
    result = asyncio.run(_run())
    log.info("risk_scoring.task_complete", **result)
    return result
