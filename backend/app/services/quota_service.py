"""Quota service for the tailored resume agent.

Free-tier rules (see docs/features/tailored-resume-agent.md §4):
  • 5 generations per day
  • 20 generations per month
  • The user's first-ever generation always succeeds, regardless of quota
    (returning students hit by a paywall on re-entry never come back).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_invocation_log import (
    QUOTA_CONSUMING_STATUSES,
    SOURCE_RESUME,
    AgentInvocationLog,
)
from app.models.generation_log import GenerationLog
from app.models.migration_gate import GATE_QUOTA_PARITY
from app.services.agent_invocation_logger import (
    has_flipped,
    record_parity_check,
)

log = structlog.get_logger()

DAILY_LIMIT = 5
MONTHLY_LIMIT = 20

# A "consumed" generation is any log row that represents a paid attempt — we
# count completed AND failed runs but NOT quota-blocked, started, or download
# events.
#
# Why `failed` counts toward quota:
#   This is deliberate anti-spam logic, not a bug. A failed generation still
#   spent tokens on the LLM (parsing, drafting, validation may have all run
#   before the failure surfaced) and still consumed the user's slot. Counting
#   it prevents a retry loop from being free.
#
#   The same rule applies to the new agent_invocation_log path: we count rows
#   where status IN ('succeeded', 'failed'). See QUOTA_CONSUMING_STATUSES on
#   the model module. Do NOT "fix" this to count successes only — please.
CONSUMING_EVENTS: tuple[str, ...] = ("completed", "failed")

QuotaReason = Literal[
    "first_resume_free",
    "within_quota",
    "daily_limit",
    "monthly_limit",
]


@dataclass(frozen=True)
class QuotaResult:
    allowed: bool
    reason: QuotaReason
    remaining_today: int
    remaining_month: int
    reset_at: datetime | None


def _start_of_day_utc(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_month_utc(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _start_of_next_day_utc(now: datetime) -> datetime:
    return _start_of_day_utc(now) + timedelta(days=1)


def _start_of_next_month_utc(now: datetime) -> datetime:
    start = _start_of_month_utc(now)
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


async def _count_events_legacy(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    since: datetime | None = None,
) -> int:
    stmt = select(func.count()).select_from(GenerationLog).where(
        GenerationLog.user_id == user_id,
        GenerationLog.event.in_(CONSUMING_EVENTS),
    )
    if since is not None:
        stmt = stmt.where(GenerationLog.created_at >= since)
    result = await db.execute(stmt)
    return int(result.scalar_one_or_none() or 0)


async def _count_events_new(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    since: datetime | None = None,
) -> int:
    stmt = select(func.count()).select_from(AgentInvocationLog).where(
        AgentInvocationLog.user_id == user_id,
        AgentInvocationLog.source == SOURCE_RESUME,
        AgentInvocationLog.status.in_(QUOTA_CONSUMING_STATUSES),
    )
    if since is not None:
        stmt = stmt.where(AgentInvocationLog.created_at >= since)
    result = await db.execute(stmt)
    return int(result.scalar_one_or_none() or 0)


async def _count_events(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    since: datetime | None = None,
) -> int:
    """Resume-quota count with parallel-read parity gate.

    During the dual-write window we run both queries on every call,
    record agreement / divergence on the gate, and return whichever
    result the gate currently trusts:

      * If the gate has flipped (>=100 consecutive agreements), trust
        agent_invocation_log — the new authoritative source.
      * Otherwise, return the legacy GenerationLog count and let the
        gate accumulate confidence in the background.

    Divergences are logged structurally and never raise. The legacy
    result remains authoritative pre-flip, so a divergence cannot break
    the user-facing path.
    """
    legacy_count = await _count_events_legacy(db, user_id=user_id, since=since)
    new_count = await _count_events_new(db, user_id=user_id, since=since)

    await record_parity_check(
        db,
        gate_name=GATE_QUOTA_PARITY,
        legacy_value=legacy_count,
        new_value=new_count,
        context={
            "user_id": str(user_id),
            "since": since.isoformat() if since else None,
        },
    )

    if await has_flipped(db, gate_name=GATE_QUOTA_PARITY):
        return new_count
    return legacy_count


async def check_quota(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> QuotaResult:
    """Return whether *user_id* can generate another tailored resume.

    First-ever generation bypasses both daily and monthly limits.
    """
    now = now or datetime.now(UTC)

    lifetime_count = await _count_events(db, user_id=user_id)
    if lifetime_count == 0:
        return QuotaResult(
            allowed=True,
            reason="first_resume_free",
            remaining_today=DAILY_LIMIT,
            remaining_month=MONTHLY_LIMIT,
            reset_at=None,
        )

    day_count = await _count_events(db, user_id=user_id, since=_start_of_day_utc(now))
    month_count = await _count_events(db, user_id=user_id, since=_start_of_month_utc(now))

    remaining_today = max(0, DAILY_LIMIT - day_count)
    remaining_month = max(0, MONTHLY_LIMIT - month_count)

    if month_count >= MONTHLY_LIMIT:
        return QuotaResult(
            allowed=False,
            reason="monthly_limit",
            remaining_today=remaining_today,
            remaining_month=0,
            reset_at=_start_of_next_month_utc(now),
        )

    if day_count >= DAILY_LIMIT:
        return QuotaResult(
            allowed=False,
            reason="daily_limit",
            remaining_today=0,
            remaining_month=remaining_month,
            reset_at=_start_of_next_day_utc(now),
        )

    return QuotaResult(
        allowed=True,
        reason="within_quota",
        remaining_today=remaining_today,
        remaining_month=remaining_month,
        reset_at=None,
    )


async def record_quota_block(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    reason: QuotaReason,
) -> None:
    """Persist a `quota_blocked` event for analytics. Never raises."""
    try:
        db.add(
            GenerationLog(
                user_id=user_id,
                event="quota_blocked",
                error_message=f"quota_blocked:{reason}",
            )
        )
        await db.commit()
    except Exception as exc:
        log.warning("quota.record_block_failed", user_id=str(user_id), error=str(exc))
