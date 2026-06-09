"""Inactivity sweep Celery task (P3 3B #152).

Beat fires weekly (Monday 09:00 UTC) and logs one `re_engagement.flagged`
structlog event per inactive student. **The events are observational only
— they are written to structlog, not to any database table** (no
event_log row, no notification, no agent_proactive_runs entry).

D16/CP1 audit (2026-05-08) verified there is NO consumer that reads
these events at chat-surface entry. Re-engagement messaging today fires
exclusively via the admin cockpit's "trigger agent" button on the per-
student detail panel, which dispatches `disrupt_prevention` directly
with an explicit `user_id`. This cron's role is to surface the inactive
cohort to operators (via log aggregation / dashboards), not to drive
auto-consumption.

Future work — wiring chat-surface auto-consumption (so a student
returning to the platform after a flag triggers `disrupt_prevention`
without admin intervention) — is tracked at
`docs/followups/d16-followup-inactivity-sweep-event-persistence.md`. It
requires either persisting flagged events to a queryable table or
adding a chat-entry hook that reads recent log events from the log
backend. Both are post-launch.
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
