"""Course / lesson resource endpoints.

Two views into the same ``lesson_resources`` table:

  GET  /courses/{id}/resources         — every resource for a course
  GET  /lessons/{id}/resources         — resources scoped to one lesson
  POST /resources/{id}/open            — resolve to a Colab/download URL,
                                         gated by enrollment

The list endpoints are public-readable but tag each row with ``locked: true``
when the requesting user is not enrolled in a paid course. The /open endpoint
hard-enforces enrollment.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, get_current_user_optional
from app.models.course import Course
from app.models.lesson import Lesson
from app.models.lesson_resource import LessonResource
from app.models.user import User
from app.repositories.enrollment_repository import EnrollmentRepository
from app.schemas.lesson_resource import LessonResourceResponse, ResourceOpenResponse
from app.services.resource_resolver import resolve_open_url

router = APIRouter(tags=["resources"])


async def _is_enrolled(
    db: AsyncSession, user: User | None, course_id: uuid.UUID
) -> bool:
    if user is None:
        return False
    enrollment = await EnrollmentRepository(db).get_by_student_and_course(
        user.id, course_id
    )
    return enrollment is not None


def _to_response(
    resource: LessonResource, *, locked: bool
) -> LessonResourceResponse:
    return LessonResourceResponse(
        id=resource.id,
        course_id=resource.course_id,
        lesson_id=resource.lesson_id,
        kind=resource.kind,  # type: ignore[arg-type]
        title=resource.title,
        description=resource.description,
        order=resource.order,
        is_required=resource.is_required,
        metadata=resource.metadata_,
        locked=locked,
    )


@router.get(
    "/courses/{course_id}/resources",
    response_model=list[LessonResourceResponse],
)
async def list_course_resources(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> list[LessonResourceResponse]:
    course = await db.get(Course, course_id)
    if course is None or course.is_deleted:
        raise HTTPException(status_code=404, detail="Course not found")

    stmt = (
        select(LessonResource)
        .where(LessonResource.course_id == course_id)
        .order_by(
            LessonResource.lesson_id.is_(None).desc(),
            LessonResource.lesson_id,
            LessonResource.order,
        )
    )
    rows = (await db.scalars(stmt)).all()

    is_paid = course.price_cents > 0
    enrolled = await _is_enrolled(db, current_user, course_id) if is_paid else True
    return [_to_response(r, locked=is_paid and not enrolled) for r in rows]


@router.get(
    "/lessons/{lesson_id}/resources",
    response_model=list[LessonResourceResponse],
)
async def list_lesson_resources(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> list[LessonResourceResponse]:
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None or lesson.is_deleted:
        raise HTTPException(status_code=404, detail="Lesson not found")

    course = await db.get(Course, lesson.course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    stmt = (
        select(LessonResource)
        .where(LessonResource.lesson_id == lesson_id)
        .order_by(LessonResource.order)
    )
    rows = (await db.scalars(stmt)).all()

    is_paid = course.price_cents > 0
    enrolled = await _is_enrolled(db, current_user, course.id) if is_paid else True
    return [_to_response(r, locked=is_paid and not enrolled) for r in rows]


@router.post(
    "/resources/{resource_id}/open",
    response_model=ResourceOpenResponse,
)
async def open_resource(
    resource_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ResourceOpenResponse:
    resource = await db.get(LessonResource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")

    course = await db.get(Course, resource.course_id)
    if course is None or course.is_deleted:
        raise HTTPException(status_code=404, detail="Course not found")

    if course.price_cents > 0 and not await _is_enrolled(db, current_user, course.id):
        raise HTTPException(
            status_code=403,
            detail="Enroll in this course to open its resources",
        )

    open_url = resolve_open_url(resource)
    return ResourceOpenResponse(kind=resource.kind, open_url=open_url)  # type: ignore[arg-type]
