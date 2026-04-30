"""F9 — Nightly outreach automation Celery task.

Runs at 09:00 UTC daily — 6 hours after F1's risk-scoring at 03:00 UTC.
That window gives the operator a chance to sanity-check the morning
queue on /admin before automated emails fly out.

The task itself is thin — all the logic lives in
`disrupt_prevention_v2_service.run_nightly_outreach`. Beat schedule
lives in `app/core/celery_app.py`.

Default behavior is dry-run (writes outreach_log rows with
status='would_send' so admin can review what WOULD have been sent).
Real sends only fire when ENV=production AND OUTREACH_AUTO_SEND=1 —
belt-and-braces against accidental fan-out.
"""

from __future__ import annotations

import asyncio

import structlog

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.services.disrupt_prevention_v2_service import run_nightly_outreach

log = structlog.get_logger()


async def _run() -> dict[str, int | bool]:
    async with AsyncSessionLocal() as session:
        result = await run_nightly_outreach(session)
    return result.as_dict()


@celery_app.task(name="app.tasks.outreach_automation.run_nightly_outreach")
def run_nightly_outreach_task() -> dict[str, int | bool]:
    """Entry point invoked by Celery Beat at 09:00 UTC daily."""
    log.info("outreach_automation.task_start")
    result = asyncio.run(_run())
    log.info("outreach_automation.task_complete", **result)
    return result
