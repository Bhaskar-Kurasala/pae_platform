"""Chat context-attach service (P1-7).

Resolves `ContextRef` tuples passed through the stream body into a structured
text prefix the LLM sees alongside the student's typed message. This mirrors
the attachment service's text-prefix path: each resolved ref is rendered as
a titled, fenced block so Claude can cite it, and the whole prefix is
concatenated ahead of the user's text.

Ownership:
  - submissions must belong to the caller (404 otherwise).
  - lessons and exercises are platform content and open to any authenticated
    student (the soft-delete guard is the only gate).

The caller caps the list at 3 refs before we even enter here; we defensively
re-clamp to 3 on the prefix side too so a future caller that forgets the
cap still can't flood the prompt.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.lesson import Lesson
from app.models.student_progress import StudentProgress
from app.schemas.context import (
    ContextRef,
    ContextSuggestionExercise,
    ContextSuggestionLesson,
    ContextSuggestionsResponse,
    ContextSuggestionSubmission,
)

log = structlog.get_logger()

MAX_CONTEXT_REFS = 3
_CODE_CAP = 6000  # chars — keep prompt bounded even on huge submissions
_DESC_CAP = 2000


class ContextAttachService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Suggestions (GET /chat/context-suggestions)
    # ------------------------------------------------------------------

    async def suggestions(
        self,
        *,
        user_id: uuid.UUID,
        lesson_id: uuid.UUID | None = None,
    ) -> ContextSuggestionsResponse:
        """Assemble the picker payload: last 5 submissions, the caller's
        current lesson (heuristic: most-recently-updated `StudentProgress`
        row, unless the caller passed `lesson_id` explicitly), and any
        in-progress exercises attached to that lesson."""
        # Recent submissions (last 5)
        sub_stmt = (
            select(ExerciseSubmission, Exercise.title)
            .join(Exercise, ExerciseSubmission.exercise_id == Exercise.id)
            .where(ExerciseSubmission.student_id == user_id)
            .order_by(ExerciseSubmission.created_at.desc())
            .limit(5)
        )
        sub_rows = (await self.db.execute(sub_stmt)).all()
        submissions = [
            ContextSuggestionSubmission(
                id=sub.id,
                exercise_title=title or "Untitled exercise",
                submitted_at=sub.created_at,
            )
            for sub, title in sub_rows
        ]

        # Current lesson — explicit override wins, otherwise heuristic.
        lesson: Lesson | None = None
        if lesson_id is not None:
            lesson = (
                await self.db.execute(
                    select(Lesson).where(
                        Lesson.id == lesson_id, Lesson.is_deleted.is_(False)
                    )
                )
            ).scalar_one_or_none()
        else:
            prog_stmt = (
                select(Lesson)
                .join(StudentProgress, StudentProgress.lesson_id == Lesson.id)
                .where(
                    StudentProgress.student_id == user_id,
                    Lesson.is_deleted.is_(False),
                )
                .order_by(StudentProgress.updated_at.desc())
                .limit(1)
            )
            lesson = (await self.db.execute(prog_stmt)).scalar_one_or_none()

        lessons = (
            [ContextSuggestionLesson(id=lesson.id, title=lesson.title)]
            if lesson is not None
            else []
        )

        # Exercises attached to the current lesson (if any) — treat them
        # as "in progress" for picker purposes.
        exercises: list[ContextSuggestionExercise] = []
        if lesson is not None:
            ex_stmt = (
                select(Exercise)
                .where(
                    Exercise.lesson_id == lesson.id,
                    Exercise.is_deleted.is_(False),
                )
                .order_by(Exercise.order)
                .limit(5)
            )
            ex_rows = (await self.db.execute(ex_stmt)).scalars().all()
            exercises = [
                ContextSuggestionExercise(id=ex.id, title=ex.title)
                for ex in ex_rows
            ]

        return ContextSuggestionsResponse(
            submissions=submissions,
            lessons=lessons,
            exercises=exercises,
        )

    # ------------------------------------------------------------------
    # Resolve refs → text prefix (stream path)
    # ------------------------------------------------------------------

    async def build_prefix(
        self,
        *,
        user_id: uuid.UUID,
        refs: Sequence[ContextRef],
    ) -> str:
        """Resolve `refs` and return a single markdown prefix string to
        prepend to the user's typed message. Empty string when `refs` is
        empty. Raises 404 when any submission doesn't belong to the caller
        or any referenced row is missing / soft-deleted."""
        if not refs:
            return ""
        clamped = list(refs)[:MAX_CONTEXT_REFS]

        blocks: list[str] = []
        for ref in clamped:
            if ref.kind == "submission":
                blocks.append(await self._render_submission(user_id, ref.id))
            elif ref.kind == "lesson":
                blocks.append(await self._render_lesson(ref.id))
            elif ref.kind == "exercise":
                blocks.append(await self._render_exercise(ref.id))
            # (Literal keeps the else path unreachable — pydantic validates.)

        return "\n\n".join(b for b in blocks if b)

    async def _render_submission(
        self, user_id: uuid.UUID, submission_id: uuid.UUID
    ) -> str:
        stmt = (
            select(ExerciseSubmission, Exercise.title)
            .join(Exercise, ExerciseSubmission.exercise_id == Exercise.id)
            .where(
                ExerciseSubmission.id == submission_id,
                ExerciseSubmission.student_id == user_id,
            )
        )
        row = (await self.db.execute(stmt)).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Context ref not found or not yours.",
            )
        sub, title = row
        code = (sub.code or "")[:_CODE_CAP]
        return (
            f"### Submission: {title or 'Untitled exercise'}\n"
            f"```python\n{code}\n```"
        )

    async def _render_lesson(self, lesson_id: uuid.UUID) -> str:
        lesson = (
            await self.db.execute(
                select(Lesson).where(
                    Lesson.id == lesson_id, Lesson.is_deleted.is_(False)
                )
            )
        ).scalar_one_or_none()
        if lesson is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Context ref not found.",
            )
        desc = (lesson.description or "")[:_DESC_CAP]
        parts = [f"### Lesson: {lesson.title}"]
        if desc:
            parts.append(desc)
        return "\n".join(parts)

    async def _render_exercise(self, exercise_id: uuid.UUID) -> str:
        ex = (
            await self.db.execute(
                select(Exercise).where(
                    Exercise.id == exercise_id, Exercise.is_deleted.is_(False)
                )
            )
        ).scalar_one_or_none()
        if ex is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Context ref not found.",
            )
        desc = (ex.description or "")[:_DESC_CAP]
        parts = [f"### Exercise: {ex.title}"]
        if desc:
            parts.append(desc)
        return "\n".join(parts)
