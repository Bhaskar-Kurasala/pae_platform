"""Inactivity sweep Celery task (P3 3B #152).

Beat fires weekly (Monday 09:00 UTC) and logs one `re_engagement.flagged`
event per inactive student. The existing `disrupt_prevention` agent
consumes these via the chat/agents surface; this cron's only job is to
surface the cohort.
"""

from __future__ import annotations

import asyncio

import structlog

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.services.inactivity_service import load_inactive_students

log = structlog.get_logger()


async def _run() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        inactive = await load_inactive_students(session)

    for student in inactive:
        log.info(
            "re_engagement.flagged",
            user_id=str(student.user_id),
            days_inactive=student.days_inactive,
        )

    log.info("re_engagement.sweep_done", flagged=len(inactive))
    return {"flagged": len(inactive)}


@celery_app.task(name="app.tasks.inactivity_sweep.sweep_inactive_students")
def sweep_inactive_students() -> dict[str, int]:
    return asyncio.run(_run())
