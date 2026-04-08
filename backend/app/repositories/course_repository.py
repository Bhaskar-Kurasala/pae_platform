import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.repositories.base import BaseRepository


class CourseRepository(BaseRepository[Course]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Course, db)

    async def get_by_slug(self, slug: str) -> Course | None:
        result = await self.db.execute(
            select(Course).where(Course.slug == slug, Course.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def list_published(self, skip: int = 0, limit: int = 50) -> list[Course]:
        result = await self.db.execute(
            select(Course)
            .where(Course.is_published.is_(True), Course.is_deleted.is_(False))
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all(self, skip: int = 0, limit: int = 100) -> list[Course]:
        result = await self.db.execute(
            select(Course).where(Course.is_deleted.is_(False)).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def get_active(self, id: str | uuid.UUID) -> Course | None:
        result = await self.db.execute(
            select(Course).where(Course.id == id, Course.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()
