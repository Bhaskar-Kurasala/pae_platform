"""Desirable difficulty (P3 3B #90).

If the student passed their last N exercise attempts on the first try,
recommend bumping difficulty one step. If they're struggling (any recent
attempt failed, or needed multiple attempts), recommend easing down.

Pure helpers at the top; async loader below.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission

_DIFFICULTY_LADDER = ("easy", "medium", "hard")
_BUMP_UP_WINDOW = 3
_EASE_DOWN_FAIL_LIMIT = 2


@dataclass(frozen=True)
class FirstTryOutcome:
    exercise_id: UUID
    passed_first_try: bool
    attempts: int


@dataclass(frozen=True)
class DifficultyRecommendation:
    current: str
    recommended: str
    reason: str


def next_difficulty(current: str) -> str:
    """Step one rung up the ladder; clamp at the top."""
    try:
        idx = _DIFFICULTY_LADDER.index(current)
    except ValueError:
        return current
    return _DIFFICULTY_LADDER[min(idx + 1, len(_DIFFICULTY_LADDER) - 1)]


def prev_difficulty(current: str) -> str:
    """Step one rung down the ladder; clamp at the bottom."""
    try:
        idx = _DIFFICULTY_LADDER.index(current)
    except ValueError:
        return current
    return _DIFFICULTY_LADDER[max(idx - 1, 0)]


def recommend_difficulty(
    current: str,
    recent: Sequence[FirstTryOutcome],
    *,
    bump_up_window: int = _BUMP_UP_WINDOW,
    ease_down_fail_limit: int = _EASE_DOWN_FAIL_LIMIT,
) -> DifficultyRecommendation:
    """Apply the desirable-difficulty rule.

    - All of the last `bump_up_window` passed first try → bump up.
    - At least `ease_down_fail_limit` of recent did not pass first try → ease down.
    - Otherwise → keep current.
    """
    if current not in _DIFFICULTY_LADDER:
        return DifficultyRecommendation(
            current=current,
            recommended=current,
            reason="Unknown difficulty level; leaving as-is",
        )

    window = list(recent)[:bump_up_window]
    non_first_try = sum(1 for o in recent if not o.passed_first_try)

    if (
        len(window) >= bump_up_window
        and all(o.passed_first_try for o in window)
        and current != _DIFFICULTY_LADDER[-1]
    ):
        return DifficultyRecommendation(
            current=current,
            recommended=next_difficulty(current),
            reason="You nailed the last 3 first-try — ready for a harder one",
        )

    if non_first_try >= ease_down_fail_limit and current != _DIFFICULTY_LADDER[0]:
        return DifficultyRecommendation(
            current=current,
            recommended=prev_difficulty(current),
            reason="Let's solidify the fundamentals before stepping back up",
        )

    return DifficultyRecommendation(
        current=current,
        recommended=current,
        reason="Holding difficulty steady",
    )


async def _recent_first_try_outcomes(
    db: AsyncSession, *, user_id: UUID, limit: int = 5
) -> list[FirstTryOutcome]:
    """For each of the student's recent distinct exercises, compute whether
    their earliest attempt passed (score >= 0.7 is "pass" per existing rubric
    elsewhere) and how many attempts they made.
    """
    result = await db.execute(
        select(
            ExerciseSubmission.exercise_id,
            ExerciseSubmission.attempt_number,
            ExerciseSubmission.score,
            ExerciseSubmission.created_at,
        )
        .where(ExerciseSubmission.student_id == user_id)
        .order_by(desc(ExerciseSubmission.created_at))
        .limit(limit * 4)
    )
    rows = list(result.all())

    seen_order: list[UUID] = []
    by_ex: dict[UUID, list[tuple[int, float | None]]] = {}
    for ex_id, attempt, score, _created in rows:
        if ex_id not in by_ex:
            seen_order.append(ex_id)
            by_ex[ex_id] = []
        by_ex[ex_id].append((attempt, score))

    outcomes: list[FirstTryOutcome] = []
    for ex_id in seen_order[:limit]:
        attempts = by_ex[ex_id]
        first = min(attempts, key=lambda t: t[0])
        passed_first = first[0] == 1 and (first[1] or 0.0) >= 0.7
        outcomes.append(
            FirstTryOutcome(
                exercise_id=ex_id,
                passed_first_try=passed_first,
                attempts=len(attempts),
            )
        )
    return outcomes


async def compute_recommendation(
    db: AsyncSession, *, user_id: UUID, exercise: Exercise
) -> DifficultyRecommendation:
    outcomes = await _recent_first_try_outcomes(db, user_id=user_id)
    return recommend_difficulty(exercise.difficulty, outcomes)


__all__ = [
    "DifficultyRecommendation",
    "FirstTryOutcome",
    "compute_recommendation",
    "next_difficulty",
    "prev_difficulty",
    "recommend_difficulty",
]
