"""Seed a tiny demo course for the Learn (lesson player) feature.

Idempotent. Run as:

    docker compose exec backend uv run python -m app.scripts.seed_learn_demo

Creates:
  * Course "Learn Demo: Python Foundations" (free, published) — entitled
    automatically to demo@pae.dev because it's free + published.
  * 3 lessons in order, each with a video asset + a learning notebook.
  * Lesson 2 requires lesson 1; lesson 3 requires lesson 2.

After this runs, /learn shows the course tile and /learn/<id> renders
the timeline with lesson 1 unlocked, lessons 2+3 locked.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.hashing import hash_password
from app.models.course import Course
from app.models.lesson import Lesson
from app.models.lesson_asset import (
    ASSET_KIND_LEARNING_NOTEBOOK,
    ASSET_KIND_PRACTICE_NOTEBOOK,
    ASSET_KIND_VIDEO,
    LessonAsset,
)
from app.models.lesson_prerequisite import LessonPrerequisite
from app.models.user import User

log = structlog.get_logger()

DEMO_EMAIL = "demo@pae.dev"
DEMO_PASSWORD = "demo-password-123"
COURSE_SLUG = "learn-demo-python-foundations"


async def _ensure_demo_user(db: AsyncSession) -> User:
    user = (
        await db.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        email=DEMO_EMAIL,
        full_name="Demo Learner",
        hashed_password=hash_password(DEMO_PASSWORD),
        role="student",
        is_verified=True,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    log.info("seed_learn.demo_user_created", id=str(user.id))
    return user


async def _ensure_course(db: AsyncSession) -> Course:
    course = (
        await db.execute(select(Course).where(Course.slug == COURSE_SLUG))
    ).scalar_one_or_none()
    if course is not None:
        return course
    course = Course(
        title="Learn Demo: Python Foundations",
        slug=COURSE_SLUG,
        description=(
            "A 3-lesson demo course wired through the Learn lesson player — "
            "video + notebook per lesson, prerequisites between lessons."
        ),
        difficulty="beginner",
        price_cents=0,
        estimated_hours=2,
        is_published=True,
    )
    db.add(course)
    await db.flush()
    log.info("seed_learn.course_created", id=str(course.id))
    return course


async def _ensure_lesson(
    db: AsyncSession, *, course_id: uuid.UUID, order: int, title: str, slug: str
) -> Lesson:
    existing = (
        await db.execute(
            select(Lesson).where(
                Lesson.course_id == course_id, Lesson.slug == slug
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    lesson = Lesson(
        course_id=course_id,
        title=title,
        slug=slug,
        description=f"Lesson {order + 1} of the Learn demo course.",
        order=order,
        is_published=True,
        duration_seconds=600,
    )
    db.add(lesson)
    await db.flush()
    return lesson


async def _ensure_asset(
    db: AsyncSession,
    *,
    lesson_id: uuid.UUID,
    kind: str,
    order: int,
    title: str,
    storage_ref: str,
    duration_seconds: int | None = None,
) -> LessonAsset:
    existing = (
        await db.execute(
            select(LessonAsset).where(
                LessonAsset.lesson_id == lesson_id,
                LessonAsset.kind == kind,
                LessonAsset.order == order,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    asset = LessonAsset(
        lesson_id=lesson_id,
        kind=kind,
        order=order,
        title=title,
        storage_ref=storage_ref,
        duration_seconds=duration_seconds,
        is_published=True,
    )
    db.add(asset)
    await db.flush()
    return asset


async def _ensure_prereq(
    db: AsyncSession,
    *,
    lesson_id: uuid.UUID,
    requires_lesson_id: uuid.UUID,
) -> None:
    existing = (
        await db.execute(
            select(LessonPrerequisite).where(
                LessonPrerequisite.lesson_id == lesson_id,
                LessonPrerequisite.requires_lesson_id == requires_lesson_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    db.add(
        LessonPrerequisite(
            lesson_id=lesson_id, requires_lesson_id=requires_lesson_id
        )
    )
    await db.flush()


async def main() -> None:
    async with AsyncSessionLocal() as db:
        user = await _ensure_demo_user(db)
        course = await _ensure_course(db)

        l1 = await _ensure_lesson(
            db, course_id=course.id, order=0,
            title="Variables & expressions", slug="variables-expressions",
        )
        l2 = await _ensure_lesson(
            db, course_id=course.id, order=1,
            title="Control flow & functions", slug="control-flow-functions",
        )
        l3 = await _ensure_lesson(
            db, course_id=course.id, order=2,
            title="Lists, dicts & comprehensions", slug="lists-dicts-comprehensions",
        )

        # Each lesson: 1 video + 1 learning notebook + 1 practice notebook.
        # storage_ref values are placeholders — Mux returns an unsigned token
        # in dev (signaling the player), and the R2 service returns a local
        # passthrough URL for notebook assets.
        for lesson, vid_id, nb_key in [
            (l1, "demo-pb-l1", "courses/learn-demo/l1.ipynb"),
            (l2, "demo-pb-l2", "courses/learn-demo/l2.ipynb"),
            (l3, "demo-pb-l3", "courses/learn-demo/l3.ipynb"),
        ]:
            await _ensure_asset(
                db, lesson_id=lesson.id, kind=ASSET_KIND_VIDEO, order=0,
                title=f"{lesson.title} — explainer", storage_ref=vid_id,
                duration_seconds=480,
            )
            await _ensure_asset(
                db, lesson_id=lesson.id, kind=ASSET_KIND_LEARNING_NOTEBOOK, order=1,
                title=f"{lesson.title} — learning notebook", storage_ref=nb_key,
            )
            await _ensure_asset(
                db, lesson_id=lesson.id, kind=ASSET_KIND_PRACTICE_NOTEBOOK, order=2,
                title=f"{lesson.title} — practice", storage_ref=nb_key.replace(".ipynb", "-practice.ipynb"),
            )

        # DAG: l1 → l2 → l3
        await _ensure_prereq(db, lesson_id=l2.id, requires_lesson_id=l1.id)
        await _ensure_prereq(db, lesson_id=l3.id, requires_lesson_id=l2.id)

        await db.commit()
        log.info(
            "seed_learn.complete",
            user_id=str(user.id),
            course_id=str(course.id),
            lessons=[str(l1.id), str(l2.id), str(l3.id)],
        )
        print("Seeded course:", course.id)
        print("Lessons:", l1.id, l2.id, l3.id)


if __name__ == "__main__":
    asyncio.run(main())
