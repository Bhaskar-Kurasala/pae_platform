"""Post-lesson retrieval quiz (P3 3A-10).

Testing effect: students retain ~2× more when forced into immediate
recall versus passive re-reading. After a student marks a lesson
complete, we hand back up to 3 MCQs drawn from the bank, prioritizing
questions attached to the exact lesson, then questions sharing the
lesson's skill.

When a student answers, each correct response nudges
`user_skill_states.confidence` up via an exponential moving average;
each miss nudges it down. Small deltas — this is a pulse, not a grade.

Kept pure-function-first: `pick_mcqs` operates on plain lists so it's
unit-testable without a DB; the async wrapper `build_quiz` does the
SQL and hands the results to the ranker.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import Lesson
from app.models.mcq_bank import MCQBank
from app.models.user_skill_state import UserSkillState

log = structlog.get_logger()


_QUIZ_SIZE = 3
# EMA weight: each correct answer contributes 20% of its signal to the
# running confidence. Low enough that one bad day doesn't tank mastery,
# high enough that sustained wrong answers drift the value meaningfully.
_CONFIDENCE_EMA_ALPHA = 0.2


@dataclass(frozen=True)
class QuizQuestion:
    """One MCQ surfaced to the client (no correct_answer leaked)."""

    id: uuid.UUID
    question: str
    options: dict[str, Any]


@dataclass(frozen=True)
class GradedAnswer:
    mcq_id: uuid.UUID
    correct: bool
    correct_answer: str
    explanation: str | None


def pick_mcqs(
    candidates: list[MCQBank],
    *,
    lesson_id: uuid.UUID,
    limit: int = _QUIZ_SIZE,
) -> list[MCQBank]:
    """Choose up to `limit` MCQs.

    Ordering: MCQs directly on the lesson first, then the rest (which
    the caller is expected to pre-filter to the lesson's skill). The
    ranker is stable — same inputs, same ordering — so tests can assert
    specific picks without worrying about DB insertion order.
    """
    on_lesson = [m for m in candidates if m.lesson_id == lesson_id]
    other = [m for m in candidates if m.lesson_id != lesson_id]
    return (on_lesson + other)[:limit]


async def build_quiz(
    db: AsyncSession, *, lesson_id: uuid.UUID
) -> list[QuizQuestion]:
    """Return up to 3 MCQs for a freshly-completed lesson.

    Tries the lesson's attached MCQs first, then widens to any MCQ on
    another lesson that shares the same `skill_id`. Empty list means
    "no bank coverage yet" — the frontend falls back to a reflection
    prompt per the 3A-10 edge-case spec.
    """
    lesson = (
        await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    ).scalar_one_or_none()
    if lesson is None:
        return []

    # Sibling lessons = same skill, different row. We then union this
    # lesson's own MCQs with MCQs on those siblings so the quiz can
    # draw from the broader skill, not just this single lesson's bank.
    sibling_ids: list[uuid.UUID] = []
    if lesson.skill_id is not None:
        sibling_rows = (
            await db.execute(
                select(Lesson.id).where(
                    Lesson.skill_id == lesson.skill_id,
                    Lesson.is_deleted.is_(False),
                )
            )
        ).scalars().all()
        sibling_ids = [sid for sid in sibling_rows if sid != lesson_id]

    lesson_ids = [lesson_id, *sibling_ids]
    rows = (
        await db.execute(
            select(MCQBank).where(
                MCQBank.lesson_id.in_(lesson_ids),
                MCQBank.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    picked = pick_mcqs(list(rows), lesson_id=lesson_id)
    return [
        QuizQuestion(id=m.id, question=m.question, options=m.options)
        for m in picked
    ]


def update_confidence_ema(current: float, correct: bool) -> float:
    """Single-step EMA for a confidence value on [0.0, 1.0].

    `correct=True` nudges toward 1.0; `correct=False` nudges toward
    0.0. Clamping is belt-and-suspenders — callers shouldn't pass
    values outside the unit interval, but if they do, we return a
    value that still fits the Float column contract.
    """
    signal = 1.0 if correct else 0.0
    nxt = (1.0 - _CONFIDENCE_EMA_ALPHA) * current + _CONFIDENCE_EMA_ALPHA * signal
    return max(0.0, min(1.0, nxt))


async def grade_answers(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    lesson_id: uuid.UUID,
    answers: dict[uuid.UUID, str],
) -> list[GradedAnswer]:
    """Grade answers, update user_skill_states.confidence, return per-Q results."""
    if not answers:
        return []

    rows = (
        await db.execute(
            select(MCQBank).where(MCQBank.id.in_(list(answers.keys())))
        )
    ).scalars().all()
    graded: list[GradedAnswer] = []
    correct_count = 0
    for m in rows:
        student_choice = answers.get(m.id, "")
        is_correct = student_choice.strip().upper() == m.correct_answer.strip().upper()
        if is_correct:
            correct_count += 1
        graded.append(
            GradedAnswer(
                mcq_id=m.id,
                correct=is_correct,
                correct_answer=m.correct_answer,
                explanation=m.explanation,
            )
        )

    lesson = (
        await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    ).scalar_one_or_none()

    if lesson is not None and lesson.skill_id is not None and graded:
        state = (
            await db.execute(
                select(UserSkillState).where(
                    UserSkillState.user_id == user_id,
                    UserSkillState.skill_id == lesson.skill_id,
                )
            )
        ).scalar_one_or_none()
        # One EMA step per answer so the mix of correct/incorrect
        # registers faithfully on the running mean.
        if state is None:
            new_confidence = 0.5  # start from neutral prior before stepping
            for g in graded:
                new_confidence = update_confidence_ema(new_confidence, g.correct)
            state = UserSkillState(
                user_id=user_id,
                skill_id=lesson.skill_id,
                confidence=new_confidence,
                mastery_level="unknown",
            )
            db.add(state)
        else:
            c = state.confidence
            for g in graded:
                c = update_confidence_ema(c, g.correct)
            state.confidence = c
        await db.commit()

    log.info(
        "lesson.retrieval_quiz_graded",
        lesson_id=str(lesson_id),
        user_id=str(user_id),
        correct=correct_count,
        total=len(graded),
    )
    return graded


__all__ = [
    "GradedAnswer",
    "QuizQuestion",
    "build_quiz",
    "grade_answers",
    "pick_mcqs",
    "update_confidence_ema",
]
