import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.schemas.progress import LessonProgressRecord, ProgressResponse
from app.schemas.retrieval_quiz import (
    GradedQuestion,
    RetrievalQuestion,
    RetrievalQuizResponse,
    RetrievalQuizResult,
    RetrievalQuizSubmission,
)
from app.services.progress_service import ProgressService
from app.services.retrieval_quiz_service import grade_answers

router = APIRouter(prefix="/students", tags=["students"])


def get_service(db: AsyncSession = Depends(get_db)) -> ProgressService:
    return ProgressService(db)


@router.get("/me/progress", response_model=ProgressResponse)
async def get_my_progress(
    service: ProgressService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> ProgressResponse:
    return await service.get_student_progress(current_user)


@router.post("/me/lessons/{lesson_id}/complete", response_model=LessonProgressRecord)
async def complete_lesson(
    lesson_id: uuid.UUID,
    service: ProgressService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> StudentProgress:
    return await service.complete_lesson(lesson_id, current_user)


@router.get(
    "/me/lessons/{lesson_id}/retrieval-quiz",
    response_model=RetrievalQuizResponse,
)
async def get_retrieval_quiz(
    lesson_id: uuid.UUID,
    service: ProgressService = Depends(get_service),
    _: User = Depends(get_current_user),
) -> RetrievalQuizResponse:
    """Up to 3 MCQs for a just-completed lesson (P3 3A-10).

    Returns an empty `questions` list when the bank has no coverage for
    the lesson's skill; the frontend uses that as its signal to fall
    back to a reflection prompt instead.
    """
    questions = await service.build_retrieval_quiz(lesson_id)
    return RetrievalQuizResponse(
        questions=[
            RetrievalQuestion(id=q.id, question=q.question, options=q.options)
            for q in questions
        ]
    )


@router.post(
    "/me/lessons/{lesson_id}/retrieval-quiz",
    response_model=RetrievalQuizResult,
)
async def submit_retrieval_quiz(
    lesson_id: uuid.UUID,
    payload: RetrievalQuizSubmission,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RetrievalQuizResult:
    """Grade the quiz and nudge user_skill_states.confidence via EMA."""
    graded = await grade_answers(
        db,
        user_id=current_user.id,
        lesson_id=lesson_id,
        answers=payload.answers,
    )
    return RetrievalQuizResult(
        correct=sum(1 for g in graded if g.correct),
        total=len(graded),
        graded=[
            GradedQuestion(
                mcq_id=g.mcq_id,
                correct=g.correct,
                correct_answer=g.correct_answer,
                explanation=g.explanation,
            )
            for g in graded
        ],
    )
