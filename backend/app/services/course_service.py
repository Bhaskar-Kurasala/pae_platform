import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.schemas.course import CourseCreate, CourseUpdate

log = structlog.get_logger()


class CourseService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = CourseRepository(db)

    def _require_admin(self, user: User) -> None:
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )

    async def list_courses(self, user: User | None = None) -> list[Course]:
        if user and user.role == "admin":
            return await self.repo.list_all()
        return await self.repo.list_published()

    async def get_course(self, course_id: str | uuid.UUID) -> Course:
        course = await self.repo.get_active(course_id)
        if not course:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
        return course

    async def create_course(self, payload: CourseCreate, user: User) -> Course:
        self._require_admin(user)
        existing = await self.repo.get_by_slug(payload.slug)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already in use")
        course = await self.repo.create(payload.model_dump())
        log.info("course.created", course_id=str(course.id), slug=course.slug)
        return course

    async def update_course(
        self, course_id: str | uuid.UUID, payload: CourseUpdate, user: User
    ) -> Course:
        self._require_admin(user)
        course = await self.get_course(course_id)
        updates = payload.model_dump(exclude_none=True)
        return await self.repo.update(course, updates)

    async def delete_course(self, course_id: str | uuid.UUID, user: User) -> None:
        self._require_admin(user)
        await self.get_course(course_id)
        await self.repo.soft_delete(course_id)
        log.info("course.deleted", course_id=str(course_id))
