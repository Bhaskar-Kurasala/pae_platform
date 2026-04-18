import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.user import User
from app.repositories.exercise_repository import ExerciseRepository, SubmissionRepository
from app.schemas.submission import SubmissionCreate

log = structlog.get_logger()


def _peer_handle(student_id: uuid.UUID | str) -> str:
    """Deterministic anonymous handle for the gallery.

    Same student → same handle across their shared submissions, so readers can
    follow a peer's reasoning across multiple attempts without us leaking the
    actual name/email.
    """
    s = str(student_id)
    return f"peer_{s.replace('-', '')[:6]}"


# P3 3A-9: the UI may submit an empty string when the student skips the
# metacognition modal; treat that as "no explanation" so the column stays
# NULL and telemetry only fires for real answers.
_MIN_SELF_EXPLANATION_CHARS = 3


def _normalize_self_explanation(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if len(stripped) < _MIN_SELF_EXPLANATION_CHARS:
        return None
    return stripped


class ExerciseService:
    def __init__(self, db: AsyncSession) -> None:
        self.exercise_repo = ExerciseRepository(db)
        self.submission_repo = SubmissionRepository(db)

    async def get_exercise(self, exercise_id: str | uuid.UUID) -> Exercise:
        exercise = await self.exercise_repo.get_active(exercise_id)
        if not exercise:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found")
        return exercise

    async def get_exercises_for_lesson(self, lesson_id: str | uuid.UUID) -> list[Exercise]:
        return await self.exercise_repo.get_by_lesson(lesson_id)

    async def submit(
        self, exercise_id: str | uuid.UUID, payload: SubmissionCreate, student: User
    ) -> ExerciseSubmission:
        exercise = await self.get_exercise(exercise_id)
        attempt = await self.submission_repo.count_attempts(student.id, exercise.id) + 1
        self_explanation = _normalize_self_explanation(payload.self_explanation)
        submission = await self.submission_repo.create(
            {
                "student_id": student.id,
                "exercise_id": exercise.id,
                "code": payload.code,
                "github_pr_url": payload.github_pr_url,
                "status": "pending",
                "attempt_number": attempt,
                "shared_with_peers": payload.shared_with_peers,
                "share_note": payload.share_note,
                "self_explanation": self_explanation,
            }
        )
        log.info(
            "exercise.submitted",
            submission_id=str(submission.id),
            student_id=str(student.id),
            attempt=attempt,
            shared=payload.shared_with_peers,
        )
        if self_explanation is not None:
            log.info(
                "exercise.self_explanation_submitted",
                exercise_id=str(exercise.id),
                submission_id=str(submission.id),
                student_id=str(student.id),
                length=len(self_explanation),
            )
        return submission

    async def list_peer_gallery(
        self,
        exercise_id: str | uuid.UUID,
        *,
        viewer_id: uuid.UUID,
        limit: int = 20,
    ) -> list[dict]:
        """Anonymized gallery of peer submissions for an exercise."""
        rows = await self.submission_repo.list_shared_for_exercise(
            exercise_id,
            exclude_student_id=viewer_id,
            limit=limit,
        )
        return [
            {
                "id": r.id,
                "code": r.code,
                "share_note": r.share_note,
                "score": r.score,
                "created_at": r.created_at,
                "author_handle": _peer_handle(r.student_id),
            }
            for r in rows
        ]

    async def update_share(
        self,
        submission_id: str | uuid.UUID,
        *,
        student_id: uuid.UUID,
        shared_with_peers: bool,
        share_note: str | None,
    ) -> ExerciseSubmission:
        submission = await self.submission_repo.get_by_id(submission_id)
        if submission is None or submission.student_id != student_id:
            raise HTTPException(status_code=404, detail="submission not found")
        return await self.submission_repo.update(
            submission,
            {"shared_with_peers": shared_with_peers, "share_note": share_note},
        )
