"""Weekly AI-authored instructor letter (P1-C-4).

Runs Sunday 01:00 UTC — one hour after growth_snapshots has populated the
current week's rows. For each user with a fresh snapshot, asks the
`progress_report` agent to draft a warm, concrete letter, then:

  1. Persists an in-app Notification (type=`weekly_letter`, unread by default)
  2. Sends the letter as email via SendGrid (if configured; otherwise skipped)

Idempotent: if a `weekly_letter` notification already exists for a user for the
same `week_ending`, the task skips that user. This means re-running on Sunday
won't spam inboxes.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from sqlalchemy import desc, select

from app.agents.base_agent import AgentState
from app.agents.progress_report import ProgressReportAgent
from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.growth_snapshot import GrowthSnapshot
from app.models.notification import Notification
from app.models.user import User
from app.services.email_service import EmailService

log = structlog.get_logger()

NOTIFICATION_TYPE = "weekly_letter"


async def _already_sent(
    db: Any, user_id: uuid.UUID, week_ending: str
) -> bool:
    """Does a prior weekly_letter notification already cover this week?

    Fetches recent `weekly_letter` notifications and checks ``metadata_`` in
    Python. We don't use a JSONB ``->>`` operator because the column is a
    generic JSON type (also runs under SQLite in tests).
    """
    rows = (
        await db.execute(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type == NOTIFICATION_TYPE,
            )
            .order_by(desc(Notification.created_at))
            .limit(10)
        )
    ).scalars().all()
    for n in rows:
        md = n.metadata_ or {}
        if md.get("week_ending") == week_ending:
            return True
    return False


async def _latest_snapshot(
    db: Any, user_id: uuid.UUID
) -> GrowthSnapshot | None:
    row = (
        await db.execute(
            select(GrowthSnapshot)
            .where(GrowthSnapshot.user_id == user_id)
            .order_by(desc(GrowthSnapshot.week_ending))
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


async def _compose_letter(
    user: User, snap: GrowthSnapshot
) -> str:
    """Invoke the progress_report agent with snapshot context and return markdown."""
    agent = ProgressReportAgent()
    payload = snap.payload if isinstance(snap.payload, dict) else {}
    state = AgentState(
        student_id=str(user.id),
        conversation_history=[],
        task=f"Weekly letter for week ending {snap.week_ending.isoformat()}",
        context={
            "lessons_completed": snap.lessons_completed,
            "skills_touched": snap.skills_touched,
            "streak_days": snap.streak_days,
            "top_concept": snap.top_concept or "",
            "quiz_scores": {
                "attempts": payload.get("quiz_attempts", 0),
                "avg": payload.get("quiz_avg_score"),
            },
            "progress": {
                "week_ending": snap.week_ending.isoformat(),
                "reflections": payload.get("reflections", 0),
            },
        },
    )
    result = await agent.execute(state)
    return result.response or ""


async def _deliver_letter(
    user: User, snap: GrowthSnapshot, email_service: EmailService
) -> dict[str, bool]:
    """Compose + persist notification + send email. Returns per-channel success."""
    body = await _compose_letter(user, snap)
    if not body.strip():
        log.warning("weekly_letter.empty_body", user_id=str(user.id))
        return {"notification": False, "email": False}

    week_ending = snap.week_ending.isoformat()

    # 1. Persist notification (in-app)
    notif_ok = False
    async with AsyncSessionLocal() as db:
        # idempotency check
        if await _already_sent(db, user.id, week_ending):
            log.info(
                "weekly_letter.skip_already_sent",
                user_id=str(user.id),
                week_ending=week_ending,
            )
            return {"notification": False, "email": False}

        notif = Notification(
            user_id=user.id,
            title=f"Your weekly note — week ending {week_ending}",
            body=body,
            notification_type=NOTIFICATION_TYPE,
            is_read=False,
            action_url="/receipts",
            metadata_={
                "week_ending": week_ending,
                "snapshot_id": str(snap.id),
            },
        )
        db.add(notif)
        await db.commit()
        notif_ok = True

    # 2. Email (best-effort; never raises)
    email_ok = False
    if user.email:
        try:
            email_ok = await email_service.send_weekly_letter(
                to_email=user.email,
                name=user.full_name or user.email.split("@")[0],
                week_ending=week_ending,
                body_markdown=body,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "weekly_letter.email_failed",
                user_id=str(user.id),
                error=str(exc),
            )

    log.info(
        "weekly_letter.delivered",
        user_id=str(user.id),
        week_ending=week_ending,
        notification=notif_ok,
        email=email_ok,
    )
    return {"notification": notif_ok, "email": email_ok}


async def _run_for_all_users() -> dict[str, int]:
    composed = 0
    skipped = 0
    failed = 0
    email_sent = 0

    async with AsyncSessionLocal() as db:
        users = list(
            (
                await db.execute(
                    select(User).where(User.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )

    # Single EmailService instance (client is thread-safe for sync SendGrid calls)
    email_service = EmailService()

    for user in users:
        async with AsyncSessionLocal() as db:
            snap = await _latest_snapshot(db, user.id)

        if snap is None:
            skipped += 1
            continue

        try:
            result = await _deliver_letter(user, snap, email_service)
            if result["notification"]:
                composed += 1
            else:
                skipped += 1
            if result["email"]:
                email_sent += 1
        except Exception as exc:  # noqa: BLE001
            log.error(
                "weekly_letter.user_failed",
                user_id=str(user.id),
                error=str(exc),
            )
            failed += 1

    log.info(
        "weekly_letter.batch_done",
        users=len(users),
        composed=composed,
        skipped=skipped,
        failed=failed,
        email_sent=email_sent,
    )
    return {
        "users": len(users),
        "composed": composed,
        "skipped": skipped,
        "failed": failed,
        "email_sent": email_sent,
    }


@celery_app.task(name="app.tasks.weekly_letters.send_weekly_letters")
def send_weekly_letters() -> dict[str, int]:
    """Celery entrypoint — runs the async batch in a fresh event loop."""
    return asyncio.run(_run_for_all_users())
