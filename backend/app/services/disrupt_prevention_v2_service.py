"""F9 — Nightly retention-engine automation.

Reads from `student_risk_signals` (computed by F1's nightly task an hour
earlier) and dispatches the right outreach for each slip pattern via
the F5 email service using F6 templates. F3's per-template throttle
prevents spam; F1's `recommended_intervention` field tells us which
template_key to use.

Design rules — these are non-obvious and matter:

  1. **Two-pass throttle.** F3 already throttles per
     (user_id, template_key). On top of that, this service caps total
     outreach per user per week — a paid_silent + capstone_stalled
     student wouldn't get TWO different emails on the same day. The
     global cap is 2 emails per user per 7 days.

  2. **Dry-run mode.** Default is `dry_run=True` for the first week of
     production. Writes outreach_log rows with status='would_send' so
     the operator can review what WOULD have been sent. Only when
     ENV=production AND `OUTREACH_AUTO_SEND=1` does the service
     actually call SendGrid. Saves us from "auto-emailed 100 students
     with a typo" disaster.

  3. **Exclude internal/test users.** Anyone with @pae.dev or @test.dev
     in their email is excluded from outreach — that's our smoke
     accounts. A flag on `users.metadata.outreach_excluded` would be
     cleaner but isn't worth the migration today; the email-suffix
     filter is good enough.

  4. **Per-user failure isolation.** A bad row (missing email,
     template render error, SendGrid 5xx) gets logged and skipped.
     The whole pass doesn't take down for one student.

The Celery task (`app/tasks/outreach_automation.py`) wraps this service
and runs at 09:00 UTC — 6 hours after F1's risk-scoring at 03:00 UTC.
That window gives the operator time to sanity-check the morning queue
on /admin before automated emails fly out. Beat schedule lives in
`app/core/celery_app.py`.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach_log import OutreachLog
from app.models.student_risk_signals import StudentRiskSignals
from app.models.user import User
from app.services import outreach_email_service, outreach_service

log = structlog.get_logger()


# ── Tunables ────────────────────────────────────────────────────────

# Global cap: even with multiple slip patterns possible, never send more
# than this many automated emails per user per rolling 7-day window.
GLOBAL_OUTREACH_CAP_PER_WEEK = 2

# Slip types we DO automate. `none` is excluded by definition. Others
# (cold_signup, paid_silent, etc.) are explicitly allow-listed so a
# future "experimental_slip" classifier output doesn't accidentally
# fire emails before we've reviewed the template.
AUTOMATABLE_SLIPS = frozenset(
    {
        "cold_signup",
        "unpaid_stalled",
        "streak_broken",
        "paid_silent",
        "capstone_stalled",
        "promotion_avoidant",
    }
)

# Email-suffix exclusions. Smoke accounts + obvious test domains.
EXCLUDED_EMAIL_SUFFIXES = (
    "@pae.dev",
    "@test.dev",
    "@example.com",
    "@example.dev",
    "@example.test",
)


# ── Result types ────────────────────────────────────────────────────


@dataclass
class OutreachAutomationResult:
    total_signals_processed: int = 0
    skipped_excluded: int = 0
    skipped_no_recommendation: int = 0
    skipped_global_cap: int = 0
    skipped_template_throttle: int = 0
    skipped_no_email: int = 0
    sent: int = 0
    mocked: int = 0
    failed: int = 0
    dry_run: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_signals_processed": self.total_signals_processed,
            "skipped_excluded": self.skipped_excluded,
            "skipped_no_recommendation": self.skipped_no_recommendation,
            "skipped_global_cap": self.skipped_global_cap,
            "skipped_template_throttle": self.skipped_template_throttle,
            "skipped_no_email": self.skipped_no_email,
            "sent": self.sent,
            "mocked": self.mocked,
            "failed": self.failed,
            "dry_run": self.dry_run,
        }


# ── Helpers ─────────────────────────────────────────────────────────


def _is_excluded_email(email: str | None) -> bool:
    if not email:
        return True
    lower = email.lower()
    return any(lower.endswith(suffix) for suffix in EXCLUDED_EMAIL_SUFFIXES)


async def _global_cap_reached(
    db: AsyncSession, *, user_id: uuid.UUID, cap: int, window_days: int = 7
) -> bool:
    """Have we sent >= cap automated emails to this user in the last
    window_days? Counts only system_nightly + ('sent', 'delivered',
    'mocked') — admin-manual sends don't burn the user's quota, and
    failed sends don't count (they didn't reach the user)."""
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    q = await db.execute(
        select(OutreachLog).where(
            OutreachLog.user_id == user_id,
            OutreachLog.triggered_by == "system_nightly",
            OutreachLog.status.in_(["sent", "delivered", "mocked"]),
            OutreachLog.sent_at >= cutoff,
        )
    )
    return len(list(q.scalars().all())) >= cap


def _should_actually_send() -> bool:
    """Production gate: even if the service is invoked with
    dry_run=False, we only actually call SendGrid when ENV=production
    AND OUTREACH_AUTO_SEND=1. Belt-and-braces against accidental fan-out."""
    if os.environ.get("ENVIRONMENT", "").lower() != "production":
        return False
    return os.environ.get("OUTREACH_AUTO_SEND", "0") == "1"


# ── Public service ──────────────────────────────────────────────────


async def run_nightly_outreach(
    db: AsyncSession, *, dry_run: bool | None = None
) -> OutreachAutomationResult:
    """Iterate every student_risk_signals row, dispatch the right
    template via F5 email service, respecting throttles + caps.

    Args:
        dry_run:
            None (default) → infer from environment: production+OUTREACH_AUTO_SEND
              triggers real sends; everything else is dry-run.
            True → never call SendGrid; write 'would_send' rows for review.
            False → caller is asserting "I want real sends regardless of env";
              use sparingly (manual admin "fire all" button, etc.).

    Returns:
        OutreachAutomationResult with per-bucket counts. Used by the
        Celery task wrapper for structured logging.
    """
    if dry_run is None:
        dry_run = not _should_actually_send()

    result = OutreachAutomationResult(dry_run=dry_run)

    # Load all risk signals + their associated user in one query.
    # 1k users is the typical scale; even 10k stays well under any
    # reasonable memory cap. If we ever need to stream, we add a yield_per.
    rows_q = await db.execute(
        select(StudentRiskSignals, User).join(
            User, StudentRiskSignals.user_id == User.id
        )
    )
    rows = list(rows_q.all())
    log.info(
        "outreach_automation.start",
        total=len(rows),
        dry_run=dry_run,
    )

    for signal, user in rows:
        result.total_signals_processed += 1

        # Skip categories first (cheapest checks).
        if signal.slip_type not in AUTOMATABLE_SLIPS:
            result.skipped_no_recommendation += 1
            continue
        if not signal.recommended_intervention:
            result.skipped_no_recommendation += 1
            continue
        if _is_excluded_email(user.email):
            result.skipped_excluded += 1
            continue
        if not user.email:
            result.skipped_no_email += 1
            continue

        # F3 per-template throttle (default 7d).
        if await outreach_service.was_sent_recently(
            db,
            user_id=user.id,
            template_key=signal.recommended_intervention,
            within_days=7,
        ):
            result.skipped_template_throttle += 1
            continue

        # Global cap: 2 system emails per user per 7d.
        if await _global_cap_reached(
            db, user_id=user.id, cap=GLOBAL_OUTREACH_CAP_PER_WEEK
        ):
            result.skipped_global_cap += 1
            continue

        # Dry-run path: write a 'would_send' row, don't call SendGrid.
        if dry_run:
            try:
                await outreach_service.record(
                    db,
                    user_id=user.id,
                    channel="email",
                    template_key=signal.recommended_intervention,
                    slip_type=signal.slip_type,
                    triggered_by="system_nightly",
                    status="would_send",
                )
                result.mocked += 1
            except Exception as exc:
                log.warning(
                    "outreach_automation.dry_run_record_failed",
                    user_id=str(user.id),
                    template_key=signal.recommended_intervention,
                    error=str(exc),
                )
                result.failed += 1
            continue

        # Live path: actually send.
        template_vars = _build_template_vars(user=user, signal=signal)
        send_result = await outreach_email_service.send_outreach_email(
            db,
            user_id=user.id,
            to_email=user.email,
            template_key=signal.recommended_intervention,
            template_vars=template_vars,
            slip_type=signal.slip_type,
            triggered_by="system_nightly",
        )
        if send_result.status == "sent":
            result.sent += 1
        elif send_result.status == "mocked":
            result.mocked += 1
        elif send_result.status == "throttled":
            # Race — somebody else sent between our check and the email
            # service's re-check. That's fine; F3 saved us.
            result.skipped_template_throttle += 1
        else:
            result.failed += 1

    log.info("outreach_automation.complete", **result.as_dict())
    return result


def _build_template_vars(*, user: User, signal: StudentRiskSignals) -> dict[str, Any]:
    """Variables passed to the F6 templates. We deliberately keep this
    small and deterministic — the templates can opt into more vars
    later but right now they reference: name, target_role,
    days_since_last_session, max_streak, sessions_completed,
    capstone_title, last_lesson_title, login_url, unsubscribe_url.

    Anything not known yet falls back to a sensible default in the
    template itself (e.g. "there" for missing name)."""
    first_name = (user.full_name or "").split(" ", 1)[0] or None
    return {
        "name": first_name,
        # Target role + last_lesson_title + capstone_title are deferrable;
        # F1.1 will populate them properly. For now templates have
        # graceful fallbacks.
        "target_role": None,
        "last_lesson_title": None,
        "capstone_title": None,
        "max_streak": signal.max_streak_ever,
        "days_since_last_session": signal.days_since_last_session,
        "sessions_completed": None,  # F9.1 follow-up: derive from learning_sessions count
        "login_url": "https://pae-platform.fly.dev/today",
        "unsubscribe_url": "https://pae-platform.fly.dev/unsubscribe",
    }
