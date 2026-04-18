"""Micro-wins for the Today screen (P3 3A-17).

"You unblocked X yesterday" — specific, verifiable, not a badge.

Surfaces the last 48h of three win kinds:
- `misconception_resolved` — a disagreement the tutor logged (3A-6 log)
- `lesson_completed` — a `student_progress` row flipped to completed
- `hard_exercise_passed` — a passing submission on `difficulty="hard"`

Pure helpers are on top (ranking/formatting) so they can be tested
without a DB. The async loader runs three independent queries and
merges them — cheap (each query is user+date-scoped and indexed).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.lesson import Lesson
from app.models.student_misconception import StudentMisconception
from app.models.student_progress import StudentProgress

WinKind = Literal[
    "misconception_resolved", "lesson_completed", "hard_exercise_passed"
]

_WINDOW_HOURS = 48
_MAX_WINS = 5


@dataclass(frozen=True)
class MicroWin:
    kind: WinKind
    label: str
    occurred_at: datetime


def window_start(now: datetime, *, hours: int = _WINDOW_HOURS) -> datetime:
    """Start of the rolling look-back window ending at `now`."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC) - timedelta(hours=hours)


def rank_wins(wins: Sequence[MicroWin], *, limit: int = _MAX_WINS) -> list[MicroWin]:
    """Newest-first, capped. Ties broken by kind name for stability."""
    ordered = sorted(
        wins,
        key=lambda w: (w.occurred_at, w.kind),
        reverse=True,
    )
    return ordered[:limit]


def format_misconception_label(topic: str) -> str:
    topic = (topic or "").strip()
    if not topic:
        return "You worked through a mistaken assumption"
    return f"You resolved a misconception about {topic}"


def format_lesson_label(title: str) -> str:
    title = (title or "").strip()
    if not title:
        return "You completed a lesson"
    return f"You finished “{title}”"


def format_hard_exercise_label(title: str) -> str:
    title = (title or "").strip()
    if not title:
        return "You passed a hard exercise"
    return f"You passed a hard exercise: “{title}”"


async def load_micro_wins(
    db: AsyncSession,
    *,
    user_id: UUID,
    now: datetime | None = None,
    limit: int = _MAX_WINS,
) -> list[MicroWin]:
    current = now or datetime.now(UTC)
    since = window_start(current)
    wins: list[MicroWin] = []

    misc_rows = await db.execute(
        select(StudentMisconception.topic, StudentMisconception.created_at).where(
            StudentMisconception.user_id == user_id,
            StudentMisconception.created_at >= since,
        )
    )
    for topic, created_at in misc_rows.all():
        wins.append(
            MicroWin(
                kind="misconception_resolved",
                label=format_misconception_label(topic),
                occurred_at=created_at,
            )
        )

    lesson_rows = await db.execute(
        select(Lesson.title, StudentProgress.completed_at)
        .join(Lesson, Lesson.id == StudentProgress.lesson_id)
        .where(
            StudentProgress.student_id == user_id,
            StudentProgress.status == "completed",
            StudentProgress.completed_at.is_not(None),
            StudentProgress.completed_at >= since,
        )
    )
    for title, completed_at in lesson_rows.all():
        wins.append(
            MicroWin(
                kind="lesson_completed",
                label=format_lesson_label(title),
                occurred_at=completed_at,
            )
        )

    sub_rows = await db.execute(
        select(Exercise.title, ExerciseSubmission.created_at)
        .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
        .where(
            ExerciseSubmission.student_id == user_id,
            ExerciseSubmission.status == "passed",
            Exercise.difficulty == "hard",
            ExerciseSubmission.created_at >= since,
        )
    )
    for title, created_at in sub_rows.all():
        wins.append(
            MicroWin(
                kind="hard_exercise_passed",
                label=format_hard_exercise_label(title),
                occurred_at=created_at,
            )
        )

    return rank_wins(wins, limit=limit)
