import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deprecated import deprecated
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.lesson import Lesson
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.schemas.lesson import LessonCreate, LessonResponse, LessonUpdate
from app.schemas.question_wall import (
    LessonQuestionsResponse,
    QuestionPostCreate,
    QuestionPostItem,
    QuestionRepliesResponse,
    QuestionVoteRequest,
)
from app.services.lesson_service import LessonService
from app.services.question_wall_service import (
    create_post,
    list_for_lesson,
    list_replies,
    record_vote,
    soft_delete_post,
)

log = structlog.get_logger()

router = APIRouter(tags=["lessons"])


def get_service(db: AsyncSession = Depends(get_db)) -> LessonService:
    return LessonService(db)


@router.get("/courses/{course_id}/lessons", response_model=list[LessonResponse])
async def list_lessons(
    course_id: uuid.UUID,
    service: LessonService = Depends(get_service),
) -> list[Lesson]:
    return await service.get_lessons_for_course(course_id)


@router.get("/lessons/{lesson_id}", response_model=LessonResponse)
async def get_lesson(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    service: LessonService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> Lesson:
    lesson = await service.get_lesson(lesson_id)
    course = await CourseRepository(db).get_active(lesson.course_id)
    if course is not None and course.price_cents > 0 and current_user.role != "admin":
        enrollment = await EnrollmentRepository(db).get_by_student_and_course(
            current_user.id, course.id
        )
        if enrollment is None:
            raise HTTPException(
                status_code=402,
                detail={
                    "reason": "enroll_required",
                    "course_id": str(course.id),
                    "price_cents": course.price_cents,
                },
            )
    return lesson


@router.post("/lessons", response_model=LessonResponse, status_code=201)
@deprecated(sunset="2026-07-01", reason="lessons created via admin tooling")
async def create_lesson(
    payload: LessonCreate,
    service: LessonService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> Lesson:
    return await service.create_lesson(payload, current_user)


@router.put("/lessons/{lesson_id}", response_model=LessonResponse)
@deprecated(sunset="2026-07-01", reason="lessons edited via admin tooling")
async def update_lesson(
    lesson_id: uuid.UUID,
    payload: LessonUpdate,
    service: LessonService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> Lesson:
    return await service.update_lesson(lesson_id, payload, current_user)


@router.get(
    "/lessons/{lesson_id}/questions",
    response_model=LessonQuestionsResponse,
)
@deprecated(sunset="2026-07-01", reason="lesson Q&A feature not in v8")
async def get_lesson_questions(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LessonQuestionsResponse:
    """Top-level questions on a lesson, ranked by upvotes (P3 3B #102)."""
    rows = await list_for_lesson(db, lesson_id=lesson_id)
    return LessonQuestionsResponse(
        lesson_id=lesson_id,
        posts=[QuestionPostItem.model_validate(r) for r in rows],
    )


@router.post(
    "/lessons/{lesson_id}/questions",
    response_model=QuestionPostItem,
    status_code=201,
)
@deprecated(sunset="2026-07-01", reason="lesson Q&A feature not in v8")
async def post_lesson_question(
    lesson_id: uuid.UUID,
    payload: QuestionPostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuestionPostItem:
    row = await create_post(
        db,
        lesson_id=lesson_id,
        author_id=current_user.id,
        body=payload.body,
        parent_id=payload.parent_id,
    )
    log.info(
        "community.question_posted",
        lesson_id=str(lesson_id),
        post_id=str(row.id),
        is_reply=row.parent_id is not None,
    )
    return QuestionPostItem.model_validate(row)


@router.get(
    "/lessons/questions/{post_id}/replies",
    response_model=QuestionRepliesResponse,
)
@deprecated(sunset="2026-07-01", reason="lesson Q&A feature not in v8")
async def get_question_replies(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuestionRepliesResponse:
    rows = await list_replies(db, parent_id=post_id)
    return QuestionRepliesResponse(
        parent_id=post_id,
        replies=[QuestionPostItem.model_validate(r) for r in rows],
    )


@router.post(
    "/lessons/questions/{post_id}/vote",
    response_model=QuestionPostItem,
)
@deprecated(sunset="2026-07-01", reason="lesson Q&A feature not in v8")
async def vote_on_question(
    post_id: uuid.UUID,
    payload: QuestionVoteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuestionPostItem:
    """Upvote or flag a question (P3 3B #102 folds #103 upvote, #108 flag)."""
    row = await record_vote(
        db, post_id=post_id, voter_id=current_user.id, kind=payload.kind
    )
    log.info(
        "community.question_voted",
        post_id=str(post_id),
        voter_id=str(current_user.id),
        kind=payload.kind,
    )
    return QuestionPostItem.model_validate(row)


@router.delete(
    "/lessons/questions/{post_id}",
    response_model=QuestionPostItem,
)
@deprecated(sunset="2026-07-01", reason="lesson Q&A feature not in v8")
async def delete_question(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuestionPostItem:
    row = await soft_delete_post(
        db, post_id=post_id, author_id=current_user.id
    )
    return QuestionPostItem.model_validate(row)
