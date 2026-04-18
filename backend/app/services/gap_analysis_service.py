"""Gap analysis for Receipts (P3 3A-16).

Honest counterweight to the weekly receipt: skills the student hasn't
touched in 21+ days whose mastery is still below 0.5. Shown on Receipts
as a small card so the student sees what they've been avoiding, not
just what they've done.

Pure-ish: the scoring is deterministic given a list of skill states. The
async loader is a thin wrapper that pulls candidate rows via SQL and then
runs the same scoring helper — so the ranking logic can be unit-tested
without a DB.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.user_skill_state import UserSkillState

log = structlog.get_logger()


# 21 days is the threshold from the ticket — it is long enough that a
# skill has genuinely faded without being so long that every struggling
# student is flagged on half their tree.
_STALE_DAYS = 21
_MASTERY_CEILING = 0.5
_DEFAULT_LIMIT = 3


@dataclass(frozen=True)
class SkillGap:
    """One gap entry for the Receipts card.

    `last_touched_at` is `None` when the student never touched the skill —
    in which case we treat the row as infinitely stale but still cap the
    age display so the UI doesn't render "2147 days ago".
    """

    skill_id: uuid.UUID
    skill_slug: str
    skill_name: str
    mastery: float
    last_touched_at: datetime | None
    days_since_touched: int


def _days_since(
    last_touched: datetime | None, now: datetime, *, never_touched_value: int = 365
) -> int:
    """Days elapsed since `last_touched`. Untouched skills return a large
    floor value so they sort to the top without overflowing the UI.
    """
    if last_touched is None:
        return never_touched_value
    # Normalize naive to UTC so tests with a naive `now` don't blow up.
    if last_touched.tzinfo is None:
        lt = last_touched.replace(tzinfo=UTC)
    else:
        lt = last_touched
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    delta = now - lt
    return max(0, delta.days)


def rank_gaps(
    states: list[tuple[UserSkillState, Skill]],
    *,
    now: datetime,
    limit: int = _DEFAULT_LIMIT,
    stale_days: int = _STALE_DAYS,
    mastery_ceiling: float = _MASTERY_CEILING,
) -> list[SkillGap]:
    """Filter + rank skill states into gap entries.

    A row qualifies when:
      - mastery/confidence is below the ceiling (default 0.5), AND
      - it was last touched more than `stale_days` ago (or never).

    Ranked by days-since-touched descending, then by lowest mastery, so
    the stalest-and-weakest skills bubble up first.
    """
    candidates: list[SkillGap] = []
    for state, skill in states:
        if state.confidence >= mastery_ceiling:
            continue
        days = _days_since(state.last_touched_at, now)
        if days <= stale_days:
            continue
        candidates.append(
            SkillGap(
                skill_id=state.skill_id,
                skill_slug=skill.slug,
                skill_name=skill.name,
                mastery=state.confidence,
                last_touched_at=state.last_touched_at,
                days_since_touched=days,
            )
        )

    candidates.sort(key=lambda g: (-g.days_since_touched, g.mastery))
    return candidates[:limit]


async def load_gaps(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[SkillGap]:
    """Async entry-point used by the receipts route."""
    current = now or datetime.now(UTC)
    rows = (
        await db.execute(
            select(UserSkillState, Skill)
            .join(Skill, UserSkillState.skill_id == Skill.id)
            .where(UserSkillState.user_id == user_id)
        )
    ).all()
    # rows is a list of Row(UserSkillState, Skill); unpack to a tuple list.
    pairs: list[tuple[UserSkillState, Skill]] = [(r[0], r[1]) for r in rows]
    gaps = rank_gaps(pairs, now=current, limit=limit)
    log.info(
        "receipts.gap_analysis_shown",
        user_id=str(user_id),
        gap_count=len(gaps),
    )
    return gaps


def format_last_touched(gap: SkillGap, *, now: datetime) -> str:
    """Human string for the Receipts card. Caps at "never" / "3+ months ago"
    so untouched and very old rows don't produce jarring copy.
    """
    if gap.last_touched_at is None:
        return "never touched"
    days = gap.days_since_touched
    if days >= 90:
        return "3+ months ago"
    if days >= 30:
        months = days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"
    if days >= 7:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    return f"{days} day{'s' if days != 1 else ''} ago"


# Re-export private constants under public names so tests and the route
# layer can read the current thresholds without duplicating magic numbers.
STALE_DAYS = _STALE_DAYS
MASTERY_CEILING = _MASTERY_CEILING


__all__ = [
    "MASTERY_CEILING",
    "STALE_DAYS",
    "SkillGap",
    "format_last_touched",
    "load_gaps",
    "rank_gaps",
]


# Keep the stale-date helper accessible for tests too.
_AGE_EPOCH = timedelta(0)
