"""Catalog route — published courses + bundles, per-user unlock state.

Mounted at ``/api/v1/catalog``. Authentication is *optional*: anonymous
callers see ``is_unlocked=False`` for everything; authenticated callers get
``is_unlocked`` populated via ``entitlement_service.is_entitled``.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user_optional
from app.models.course import Course
from app.models.course_bundle import CourseBundle
from app.models.user import User
from app.schemas.payments_v2 import (
    CatalogBundleResponse,
    CatalogCourseResponse,
    CatalogResponse,
)
from app.services import entitlement_service

log = structlog.get_logger()

router = APIRouter(prefix="/catalog", tags=["catalog"])


# Difficulty sort key — same ordering used elsewhere in the platform so the
# catalog page stays consistent with the courses dashboard.
_DIFFICULTY_RANK = {
    "beginner": 0,
    "intermediate": 1,
    "advanced": 2,
    "expert": 3,
}


@router.get("/", response_model=CatalogResponse)
async def get_catalog(
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> CatalogResponse:
    course_stmt = select(Course).where(
        Course.is_published.is_(True),
        Course.is_deleted.is_(False),
    )
    course_rows = list((await db.execute(course_stmt)).scalars().all())
    course_rows.sort(
        key=lambda c: (
            _DIFFICULTY_RANK.get(c.difficulty, 99),
            c.title.lower(),
        )
    )

    courses_out: list[CatalogCourseResponse] = []
    for course in course_rows:
        unlocked = False
        if current_user is not None:
            unlocked = await entitlement_service.is_entitled(
                db, user_id=current_user.id, course_id=course.id
            )
        courses_out.append(
            CatalogCourseResponse(
                id=course.id,
                slug=course.slug,
                title=course.title,
                description=course.description,
                price_cents=course.price_cents,
                currency=settings.payments_default_currency,
                is_published=course.is_published,
                difficulty=course.difficulty,
                bullets=list(course.bullets or []),
                metadata=dict(course.metadata_ or {}),
                is_unlocked=unlocked,
            )
        )

    bundle_stmt = (
        select(CourseBundle)
        .where(CourseBundle.is_published.is_(True))
        .order_by(CourseBundle.sort_order, CourseBundle.title)
    )
    bundle_rows = list((await db.execute(bundle_stmt)).scalars().all())

    bundles_out: list[CatalogBundleResponse] = []
    for bundle in bundle_rows:
        # course_ids is stored as JSON list[str]; normalise to UUIDs and drop
        # bad rows (logged in entitlement_service.expand_bundle).
        course_ids: list = []
        for raw in bundle.course_ids or []:
            try:
                import uuid as _uuid

                course_ids.append(_uuid.UUID(str(raw)))
            except (ValueError, TypeError):
                continue
        bundles_out.append(
            CatalogBundleResponse(
                id=bundle.id,
                slug=bundle.slug,
                title=bundle.title,
                description=bundle.description,
                price_cents=bundle.price_cents,
                currency=bundle.currency or settings.payments_default_currency,
                course_ids=course_ids,
                metadata=dict(bundle.metadata_ or {}),
                is_published=bundle.is_published,
            )
        )

    return CatalogResponse(courses=courses_out, bundles=bundles_out)
