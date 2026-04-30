import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
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
from app.services import student_message_service
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


@router.delete(
    "/me/lessons/{lesson_id}/complete",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def uncomplete_lesson(
    lesson_id: uuid.UUID,
    service: ProgressService = Depends(get_service),
    current_user: User = Depends(get_current_user),
) -> None:
    await service.uncomplete_lesson(lesson_id, current_user)


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


# ── F8 — In-app messaging (student side) ────────────────────────────


class _MessageRead(BaseModel):
    id: str
    thread_id: str
    student_id: str
    sender_role: str
    sender_id: str | None
    body: str
    read_at: str | None
    created_at: str


def _msg_to_read(m: Any) -> _MessageRead:
    return _MessageRead(
        id=str(m.id),
        thread_id=str(m.thread_id),
        student_id=str(m.student_id),
        sender_role=m.sender_role,
        sender_id=str(m.sender_id) if m.sender_id else None,
        body=m.body,
        read_at=m.read_at.isoformat() if m.read_at else None,
        created_at=m.created_at.isoformat(),
    )


class _ThreadSummary(BaseModel):
    thread_id: str
    last_message_preview: str
    last_message_at: str
    last_sender_role: str
    unread_count: int


class _UnreadCount(BaseModel):
    unread: int


class _StudentReply(BaseModel):
    thread_id: str = Field(..., description="Existing thread to reply in")
    body: str = Field(..., min_length=1, max_length=5000)


@router.get("/me/messages/unread-count", response_model=_UnreadCount)
async def get_my_unread_message_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> _UnreadCount:
    """Polled every 60s by the F8 banner. Indexed query — cheap."""
    n = await student_message_service.unread_count_for_student(
        db, student_id=current_user.id
    )
    return _UnreadCount(unread=n)


@router.get("/me/messages", response_model=list[_ThreadSummary])
async def list_my_message_threads(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[_ThreadSummary]:
    """Student inbox: one row per thread, latest message preview each."""
    threads = await student_message_service.list_threads_for_student(
        db, student_id=current_user.id
    )
    return [
        _ThreadSummary(
            thread_id=str(t["thread_id"]),
            last_message_preview=t["last_message_preview"],
            last_message_at=t["last_message_at"].isoformat(),
            last_sender_role=t["last_sender_role"],
            unread_count=t["unread_count"],
        )
        for t in threads
    ]


@router.get("/me/messages/{thread_id}", response_model=list[_MessageRead])
async def get_my_thread(
    thread_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[_MessageRead]:
    """Detail view of one thread. Auth-scoped: we filter by student_id
    so a user can't load another student's thread by guessing UUIDs."""
    msgs = await student_message_service.list_thread(
        db, thread_id=thread_id
    )
    msgs = [m for m in msgs if m.student_id == current_user.id]
    if not msgs:
        # Either thread doesn't exist or it's not theirs. Same response
        # so we don't leak existence of other students' threads.
        raise HTTPException(status_code=404, detail="thread not found")
    return [_msg_to_read(m) for m in msgs]


@router.post(
    "/me/messages",
    response_model=_MessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def reply_to_thread(
    payload: _StudentReply = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> _MessageRead:
    """Student reply. Validates the thread belongs to them, creates
    the message, AND flips the originating outreach_log row's
    replied_at to close the F3 audit-trail loop."""
    thread_uuid = uuid.UUID(payload.thread_id)
    # Validate the thread exists and belongs to this student.
    existing = await student_message_service.list_thread(
        db, thread_id=thread_uuid, limit=1
    )
    if not existing or existing[0].student_id != current_user.id:
        raise HTTPException(status_code=404, detail="thread not found")
    msg = await student_message_service.create_message(
        db,
        thread_id=thread_uuid,
        student_id=current_user.id,
        sender_role="student",
        sender_id=current_user.id,
        body=payload.body,
    )
    return _msg_to_read(msg)


@router.post(
    "/me/messages/{thread_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def mark_my_thread_read(
    thread_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Mark all admin messages in this thread as read."""
    # Verify ownership before flipping read_at.
    msgs = await student_message_service.list_thread(
        db, thread_id=thread_id, limit=1
    )
    if not msgs or msgs[0].student_id != current_user.id:
        raise HTTPException(status_code=404, detail="thread not found")
    await student_message_service.mark_thread_read(
        db, thread_id=thread_id, reader_user_id=current_user.id
    )
