"""Weekly growth snapshot Celery task (P1-C-2).

Beat fires `build_weekly_snapshots` every Sunday at 00:00 UTC. The task
iterates every active, non-deleted user and writes one `growth_snapshots`
row per user covering the week that just ended (Mon–Sun UTC).

Idempotent: re-running is safe because upsert is keyed on (user_id,
week_ending).
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.services.growth_snapshot_service import build_and_persist

log = structlog.get_logger()


async def _run_for_all_users() -> dict[str, int]:
    written = 0
    failed = 0
    async with AsyncSessionLocal() as session:
        users_q = select(User.id).where(User.is_active.is_(True))
        user_ids: list[uuid.UUID] = list(
            (await session.execute(users_q)).scalars().all()
        )

    for uid in user_ids:
        async with AsyncSessionLocal() as session:
            try:
                await build_and_persist(session, uid)
                written += 1
            except Exception as exc:  # noqa: BLE001 — we want to keep going
                log.error(
                    "growth_snapshot.user_failed", user_id=str(uid), error=str(exc)
                )
                failed += 1

    log.info(
        "growth_snapshot.batch_done",
        users=len(user_ids),
        written=written,
        failed=failed,
    )
    return {"users": len(user_ids), "written": written, "failed": failed}


@celery_app.task(name="app.tasks.growth_snapshots.build_weekly_snapshots")
def build_weekly_snapshots() -> dict[str, int]:
    """Celery entrypoint — runs the async batch inside a fresh event loop."""
    return asyncio.run(_run_for_all_users())
