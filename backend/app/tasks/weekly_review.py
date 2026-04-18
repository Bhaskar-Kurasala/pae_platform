"""Weekly review quiz Celery task (P3 3B #93).

Beat fires `assemble_weekly_reviews` every Sunday at 02:00 UTC — 1h
after weekly-letters, so students returning to the app on Monday find
a pre-built review quiz waiting from due SRS cards.

This task only *assembles* the quiz and logs the count; actual delivery
to the student is done via the on-demand `/review/weekly` endpoint or
via weekly-letters integration.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.services.weekly_review_service import build_weekly_review

log = structlog.get_logger()


async def _run_for_all_users() -> dict[str, int]:
    assembled = 0
    empty = 0
    failed = 0
    async with AsyncSessionLocal() as session:
        users_q = select(User.id).where(User.is_active.is_(True))
        user_ids: list[uuid.UUID] = list(
            (await session.execute(users_q)).scalars().all()
        )

    for uid in user_ids:
        async with AsyncSessionLocal() as session:
            try:
                quiz = await build_weekly_review(session, user_id=uid)
                if quiz.cards:
                    assembled += 1
                    log.info(
                        "review.weekly_assembled",
                        user_id=str(uid),
                        cards=len(quiz.cards),
                    )
                else:
                    empty += 1
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "review.weekly_failed", user_id=str(uid), error=str(exc)
                )
                failed += 1

    log.info(
        "review.weekly_batch_done",
        users=len(user_ids),
        assembled=assembled,
        empty=empty,
        failed=failed,
    )
    return {
        "users": len(user_ids),
        "assembled": assembled,
        "empty": empty,
        "failed": failed,
    }


@celery_app.task(name="app.tasks.weekly_review.assemble_weekly_reviews")
def assemble_weekly_reviews() -> dict[str, int]:
    return asyncio.run(_run_for_all_users())
