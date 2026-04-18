"""Weekly review quiz — the testing effect (P3 3B #93).

Assemble a small (≤10) review quiz from the student's SRS cards that are
due this week. Prioritises the most-overdue cards first and caps the
total so the review stays <10 minutes.

Pure helpers on top; async loader + Celery-friendly batch below.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.srs_card import SRSCard

_MAX_QUIZ_ITEMS = 10
_REVIEW_WINDOW_DAYS = 7


@dataclass(frozen=True)
class ReviewCard:
    card_id: UUID
    concept_key: str
    prompt: str
    days_overdue: int


@dataclass(frozen=True)
class WeeklyReviewQuiz:
    user_id: UUID
    generated_at: datetime
    cards: tuple[ReviewCard, ...]


def compute_days_overdue(
    next_due_at: datetime, *, now: datetime
) -> int:
    """Whole days past the due date; 0 for not-yet-due."""
    if next_due_at.tzinfo is None:
        next_due_at = next_due_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = now - next_due_at
    return max(0, delta.days)


def rank_due_cards(
    cards: Iterable[ReviewCard], *, limit: int = _MAX_QUIZ_ITEMS
) -> list[ReviewCard]:
    """Most overdue first, then stable by card_id."""
    return sorted(
        cards, key=lambda c: (-c.days_overdue, str(c.card_id))
    )[:limit]


def assemble_quiz(
    user_id: UUID,
    due: Sequence[ReviewCard],
    *,
    now: datetime,
    limit: int = _MAX_QUIZ_ITEMS,
) -> WeeklyReviewQuiz:
    return WeeklyReviewQuiz(
        user_id=user_id,
        generated_at=now,
        cards=tuple(rank_due_cards(due, limit=limit)),
    )


async def _load_due_cards(
    db: AsyncSession,
    *,
    user_id: UUID,
    now: datetime,
    window_days: int = _REVIEW_WINDOW_DAYS,
) -> list[ReviewCard]:
    """All cards due within the window (including previously-missed)."""
    threshold = now + timedelta(days=0)  # only genuinely overdue/due-today
    _ = window_days  # reserved for future "upcoming-this-week" expansion
    result = await db.execute(
        select(
            SRSCard.id,
            SRSCard.concept_key,
            SRSCard.prompt,
            SRSCard.next_due_at,
        ).where(
            SRSCard.user_id == user_id,
            SRSCard.next_due_at <= threshold,
        )
    )
    cards: list[ReviewCard] = []
    for card_id, concept_key, prompt, next_due_at in result.all():
        cards.append(
            ReviewCard(
                card_id=card_id,
                concept_key=concept_key,
                prompt=prompt,
                days_overdue=compute_days_overdue(next_due_at, now=now),
            )
        )
    return cards


async def build_weekly_review(
    db: AsyncSession,
    *,
    user_id: UUID,
    now: datetime | None = None,
) -> WeeklyReviewQuiz:
    effective_now = now or datetime.now(timezone.utc)
    due = await _load_due_cards(db, user_id=user_id, now=effective_now)
    return assemble_quiz(user_id, due, now=effective_now)


__all__ = [
    "ReviewCard",
    "WeeklyReviewQuiz",
    "assemble_quiz",
    "build_weekly_review",
    "compute_days_overdue",
    "rank_due_cards",
]
