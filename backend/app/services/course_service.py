import contextlib
import json
import uuid
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.user import User
from app.repositories.course_repository import CourseRepository
from app.schemas.course import CourseCreate, CourseUpdate

log = structlog.get_logger()

_COURSES_TTL = 300  # 5 minutes


def _courses_cache_key() -> str:
    from app.core.redis import namespaced_key

    return namespaced_key("courses", "published")


async def _get_redis_optional() -> Any:
    with contextlib.suppress(Exception):
        from app.core.redis import get_redis

        return await get_redis()  # type: ignore[return-value]
    return None


async def _invalidate_courses_cache() -> None:
    redis = await _get_redis_optional()
    if redis:
        with contextlib.suppress(Exception):
            await redis.delete(_courses_cache_key())  # type: ignore[union-attr]


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

        # Check Redis cache for published courses (warm path)
        redis = await _get_redis_optional()
        if redis:
            with contextlib.suppress(Exception):
                cached = await redis.get(_courses_cache_key())  # type: ignore[union-attr]
                if cached:
                    log.debug("courses.cache.hit")
                    # Cache is populated; still return fresh ORM objects for type safety
                    # A full JSON→response bypass would require endpoint-level caching

        courses = await self.repo.list_published()

        # Populate cache
        if redis and courses:
            with contextlib.suppress(Exception):
                serializable = [
                    {"id": str(c.id), "title": c.title, "slug": c.slug, "difficulty": c.difficulty}
                    for c in courses
                ]
                await redis.setex(_courses_cache_key(), _COURSES_TTL, json.dumps(serializable))  # type: ignore[union-attr]
                log.debug("courses.cache.populated", count=len(courses))

        return courses

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
        await _invalidate_courses_cache()
        log.info("course.created", course_id=str(course.id), slug=course.slug)
        return course

    async def update_course(
        self, course_id: str | uuid.UUID, payload: CourseUpdate, user: User
    ) -> Course:
        self._require_admin(user)
        course = await self.get_course(course_id)
        updated = await self.repo.update(course, payload.model_dump(exclude_none=True))
        await _invalidate_courses_cache()
        return updated

    async def delete_course(self, course_id: str | uuid.UUID, user: User) -> None:
        self._require_admin(user)
        await self.get_course(course_id)
        await self.repo.soft_delete(course_id)
        await _invalidate_courses_cache()
        log.info("course.deleted", course_id=str(course_id))
