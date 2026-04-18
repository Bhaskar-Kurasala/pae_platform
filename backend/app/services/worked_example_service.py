"""Worked examples (P3 3B #91).

When the student is stuck on an exercise, surface a worked example of a
*similar* problem — defined as another exercise in the same skill where
the student (or anyone) already posted a well-scored, shared submission.

Pure helpers on top; async loaders below.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission

_MIN_SCORE_FOR_EXAMPLE = 70  # score is stored as int 0-100
_MAX_CODE_SNIPPET_CHARS = 2000


@dataclass(frozen=True)
class WorkedExampleCandidate:
    submission_id: UUID
    exercise_id: UUID
    exercise_title: str
    score: int
    code: str
    share_note: str | None
    is_own: bool


@dataclass(frozen=True)
class WorkedExample:
    exercise_title: str
    code_snippet: str
    note: str | None
    source: str  # "your earlier solution" | "peer solution"


def rank_candidates(
    candidates: Iterable[WorkedExampleCandidate],
    *,
    current_exercise_id: UUID,
) -> list[WorkedExampleCandidate]:
    """Filter the current exercise out, sort by (own first, then score desc)."""
    pool = [c for c in candidates if c.exercise_id != current_exercise_id]
    return sorted(pool, key=lambda c: (not c.is_own, -c.score))


def trim_code(code: str, *, limit: int = _MAX_CODE_SNIPPET_CHARS) -> str:
    """Keep code small enough to fit in an expandable UI block."""
    if len(code) <= limit:
        return code
    return code[:limit] + "\n# …(truncated)"


def to_worked_example(
    candidate: WorkedExampleCandidate,
) -> WorkedExample:
    source = "your earlier solution" if candidate.is_own else "peer solution"
    return WorkedExample(
        exercise_title=candidate.exercise_title,
        code_snippet=trim_code(candidate.code),
        note=candidate.share_note,
        source=source,
    )


async def _candidates_for_skill(
    db: AsyncSession,
    *,
    skill_id: UUID,
    viewer_id: UUID,
    limit: int = 10,
) -> list[WorkedExampleCandidate]:
    """Pull scored submissions for exercises in the same skill.

    Own submissions are always eligible; others only if `shared_with_peers`.
    """
    stmt = (
        select(
            ExerciseSubmission.id,
            ExerciseSubmission.exercise_id,
            Exercise.title,
            ExerciseSubmission.score,
            ExerciseSubmission.code,
            ExerciseSubmission.share_note,
            ExerciseSubmission.student_id,
        )
        .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
        .where(
            and_(
                Exercise.skill_id == skill_id,
                ExerciseSubmission.score != None,  # noqa: E711
                ExerciseSubmission.score >= _MIN_SCORE_FOR_EXAMPLE,
                ExerciseSubmission.code != None,  # noqa: E711
            )
        )
        .order_by(desc(ExerciseSubmission.score), desc(ExerciseSubmission.created_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    out: list[WorkedExampleCandidate] = []
    for sub_id, ex_id, title, score, code, note, student_id in result.all():
        is_own = student_id == viewer_id
        if not is_own:
            # Check share flag on a second fetch would be wasteful; we already
            # have it — re-query with joined share filter when not own.
            pass
        out.append(
            WorkedExampleCandidate(
                submission_id=sub_id,
                exercise_id=ex_id,
                exercise_title=title,
                score=score,
                code=code or "",
                share_note=note,
                is_own=is_own,
            )
        )
    return out


async def _shared_filter_pass(
    db: AsyncSession,
    candidates: list[WorkedExampleCandidate],
    *,
    viewer_id: UUID,
) -> list[WorkedExampleCandidate]:
    """Drop non-own candidates whose submissions aren't shared with peers."""
    if not candidates:
        return []
    non_own_ids = [c.submission_id for c in candidates if not c.is_own]
    if not non_own_ids:
        return candidates
    result = await db.execute(
        select(ExerciseSubmission.id).where(
            and_(
                ExerciseSubmission.id.in_(non_own_ids),
                ExerciseSubmission.shared_with_peers.is_(True),
            )
        )
    )
    shared_ids = {row[0] for row in result.all()}
    return [c for c in candidates if c.is_own or c.submission_id in shared_ids]


async def fetch_worked_example(
    db: AsyncSession, *, user_id: UUID, exercise: Exercise
) -> WorkedExample | None:
    if exercise.skill_id is None:
        return None
    raw = await _candidates_for_skill(
        db, skill_id=exercise.skill_id, viewer_id=user_id
    )
    filtered = await _shared_filter_pass(db, raw, viewer_id=user_id)
    ranked = rank_candidates(filtered, current_exercise_id=exercise.id)
    if not ranked:
        return None
    return to_worked_example(ranked[0])


__all__ = [
    "WorkedExample",
    "WorkedExampleCandidate",
    "fetch_worked_example",
    "rank_candidates",
    "to_worked_example",
    "trim_code",
]
