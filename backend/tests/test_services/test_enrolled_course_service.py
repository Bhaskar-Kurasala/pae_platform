"""EnrolledCourseService — last-touched ordering + progress-pct rollup."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.course import Course
from app.models.lesson import Lesson
from app.models.lesson_asset import (
    ASSET_KIND_LEARNING_NOTEBOOK,
    ASSET_KIND_VIDEO,
    LessonAsset,
)
from app.models.student_asset_progress import StudentAssetProgress
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.services import enrolled_course_service


@pytest.fixture
async def two_courses(db_session):
    user = User(
        email=f"enrolled-{uuid.uuid4().hex[:8]}@test.dev",
        hashed_password="x",
        role="student",
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    cA = Course(
        title="Course A", slug=f"a-{uuid.uuid4().hex[:8]}", description="d",
        difficulty="beginner", price_cents=0, is_published=True,
    )
    cB = Course(
        title="Course B", slug=f"b-{uuid.uuid4().hex[:8]}", description="d",
        difficulty="beginner", price_cents=0, is_published=True,
    )
    db_session.add_all([cA, cB])
    await db_session.flush()

    # Each course has 2 lessons, each lesson 1 video asset.
    lessons = []
    assets = []
    for course in (cA, cB):
        for i in range(2):
            l = Lesson(
                course_id=course.id, title=f"L{i}", slug=f"l{i}-{uuid.uuid4().hex[:6]}",
                order=i, is_published=True,
            )
            db_session.add(l)
            lessons.append(l)
        await db_session.flush()
    for l in lessons:
        a = LessonAsset(
            lesson_id=l.id, kind=ASSET_KIND_VIDEO, order=0,
            title="v", storage_ref="pb",
        )
        db_session.add(a)
        assets.append(a)
    await db_session.flush()

    return SimpleNamespace(user=user, courseA=cA, courseB=cB, lessons=lessons, assets=assets)


@pytest.mark.asyncio
async def test_no_progress_means_no_enrollments(db_session, two_courses):
    rows = await enrolled_course_service.list_enrolled_courses(
        db_session, student_id=two_courses.user.id
    )
    assert rows == []
    assert (
        await enrolled_course_service.active_course(
            db_session, student_id=two_courses.user.id
        )
    ) is None


@pytest.mark.asyncio
async def test_touching_course_b_makes_it_active(db_session, two_courses):
    # Touch one asset in course B only.
    asset_b = next(
        a for a in two_courses.assets
        if any(l.id == a.lesson_id and l.course_id == two_courses.courseB.id for l in two_courses.lessons)
    )
    db_session.add(
        StudentAssetProgress(
            student_id=two_courses.user.id, asset_id=asset_b.id,
            status="in_progress", watch_pct=0.2,
        )
    )
    await db_session.flush()

    rows = await enrolled_course_service.list_enrolled_courses(
        db_session, student_id=two_courses.user.id
    )
    assert len(rows) == 1
    assert rows[0].course_id == two_courses.courseB.id

    active = await enrolled_course_service.active_course(
        db_session, student_id=two_courses.user.id
    )
    assert active is not None
    assert active.course_id == two_courses.courseB.id


@pytest.mark.asyncio
async def test_most_recently_touched_wins(db_session, two_courses):
    asset_a = next(
        a for a in two_courses.assets
        if any(l.id == a.lesson_id and l.course_id == two_courses.courseA.id for l in two_courses.lessons)
    )
    asset_b = next(
        a for a in two_courses.assets
        if any(l.id == a.lesson_id and l.course_id == two_courses.courseB.id for l in two_courses.lessons)
    )

    older = datetime.now(UTC) - timedelta(days=2)
    newer = datetime.now(UTC)

    pa = StudentAssetProgress(
        student_id=two_courses.user.id, asset_id=asset_a.id,
        status="in_progress", watch_pct=0.5,
    )
    pb = StudentAssetProgress(
        student_id=two_courses.user.id, asset_id=asset_b.id,
        status="in_progress", watch_pct=0.1,
    )
    db_session.add_all([pa, pb])
    await db_session.flush()
    pa.updated_at = older
    pb.updated_at = newer
    await db_session.flush()

    rows = await enrolled_course_service.list_enrolled_courses(
        db_session, student_id=two_courses.user.id
    )
    assert [r.course_id for r in rows] == [
        two_courses.courseB.id,
        two_courses.courseA.id,
    ]


@pytest.mark.asyncio
async def test_progress_pct_reflects_completed_lessons(db_session, two_courses):
    # Course A: complete one of the two lessons via a StudentProgress row.
    lesson_a0 = next(
        l for l in two_courses.lessons if l.course_id == two_courses.courseA.id
    )
    asset_a = next(
        a for a in two_courses.assets if a.lesson_id == lesson_a0.id
    )
    db_session.add_all(
        [
            StudentAssetProgress(
                student_id=two_courses.user.id, asset_id=asset_a.id,
                status="completed", watch_pct=1.0,
                completed_at=datetime.now(UTC),
            ),
            StudentProgress(
                student_id=two_courses.user.id, lesson_id=lesson_a0.id,
                status="completed", completed_at=datetime.now(UTC),
            ),
        ]
    )
    await db_session.flush()

    rows = await enrolled_course_service.list_enrolled_courses(
        db_session, student_id=two_courses.user.id
    )
    assert len(rows) == 1
    assert rows[0].total_lessons == 2
    assert rows[0].completed_lessons == 1
    assert rows[0].progress_pct == pytest.approx(0.5)
