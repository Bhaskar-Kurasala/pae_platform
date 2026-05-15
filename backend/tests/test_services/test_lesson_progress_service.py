"""Integration tests for LessonProgressService.

Verifies asset progress upserts, lesson rollup, and the
"newly unlocked" diff after a completion cascades.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models.course import Course
from app.models.lesson import Lesson
from app.models.lesson_asset import (
    ASSET_KIND_LEARNING_NOTEBOOK,
    ASSET_KIND_VIDEO,
    LessonAsset,
)
from app.models.lesson_prerequisite import LessonPrerequisite
from app.models.user import User
from app.services import lesson_access_service, lesson_progress_service
from app.services.lesson_progress_service import AssetProgressDelta


@pytest.fixture
async def two_lesson_chain(db_session):
    user = User(
        email=f"prog-{uuid.uuid4().hex[:8]}@test.dev",
        hashed_password="x",
        role="student",
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    course = Course(
        title="Chain",
        slug=f"chain-{uuid.uuid4().hex[:8]}",
        description="d",
        difficulty="beginner",
        price_cents=0,
        is_published=True,
    )
    db_session.add(course)
    await db_session.flush()

    a = Lesson(
        course_id=course.id, title="A", slug="a", order=0, is_published=True
    )
    b = Lesson(
        course_id=course.id, title="B", slug="b", order=1, is_published=True
    )
    db_session.add_all([a, b])
    await db_session.flush()

    a_video = LessonAsset(
        lesson_id=a.id,
        kind=ASSET_KIND_VIDEO,
        order=0,
        title="A video",
        storage_ref="pb_a",
    )
    a_nb = LessonAsset(
        lesson_id=a.id,
        kind=ASSET_KIND_LEARNING_NOTEBOOK,
        order=1,
        title="A nb",
        storage_ref="a.ipynb",
    )
    b_video = LessonAsset(
        lesson_id=b.id,
        kind=ASSET_KIND_VIDEO,
        order=0,
        title="B video",
        storage_ref="pb_b",
    )
    db_session.add_all([a_video, a_nb, b_video])
    await db_session.flush()
    db_session.add(LessonPrerequisite(lesson_id=b.id, requires_lesson_id=a.id))
    await db_session.flush()

    return SimpleNamespace(
        user=user, course=course, a=a, b=b, a_video=a_video, a_nb=a_nb, b_video=b_video,
    )


@pytest.mark.asyncio
async def test_apply_asset_delta_marks_notebook_executed(
    db_session, two_lesson_chain
):
    res = await lesson_progress_service.apply_asset_delta(
        db_session,
        student_id=two_lesson_chain.user.id,
        asset_id=two_lesson_chain.a_nb.id,
        delta=AssetProgressDelta(mark_executed=True),
    )
    assert res.asset_progress.executed_at is not None
    assert res.asset_progress.execution_count == 1
    assert res.asset_progress.status == "completed"
    assert res.lesson_completed_now is False  # video still missing


@pytest.mark.asyncio
async def test_completing_all_assets_unlocks_next_lesson(
    db_session, two_lesson_chain
):
    # 1) execute notebook
    await lesson_progress_service.apply_asset_delta(
        db_session,
        student_id=two_lesson_chain.user.id,
        asset_id=two_lesson_chain.a_nb.id,
        delta=AssetProgressDelta(mark_executed=True),
    )
    # 2) watch video to threshold
    res = await lesson_progress_service.apply_asset_delta(
        db_session,
        student_id=two_lesson_chain.user.id,
        asset_id=two_lesson_chain.a_video.id,
        delta=AssetProgressDelta(watch_pct=0.95, watched_seconds=570),
    )
    assert res.lesson_completed_now is True
    assert two_lesson_chain.b.id in res.newly_unlocked_lesson_ids

    # Verify via the access service that B is now unlocked.
    states = await lesson_access_service.build_course_state(
        db_session,
        student_id=two_lesson_chain.user.id,
        course_id=two_lesson_chain.course.id,
    )
    by_id = {s.lesson.id: s for s in states}
    assert by_id[two_lesson_chain.a.id].lock_state == "completed"
    assert by_id[two_lesson_chain.b.id].lock_state == "unlocked"


@pytest.mark.asyncio
async def test_watch_pct_is_monotonic(db_session, two_lesson_chain):
    # First update to 0.9
    await lesson_progress_service.apply_asset_delta(
        db_session,
        student_id=two_lesson_chain.user.id,
        asset_id=two_lesson_chain.a_video.id,
        delta=AssetProgressDelta(watch_pct=0.9),
    )
    # Then a "rewind" that sends 0.3 — must NOT lower the recorded pct.
    res = await lesson_progress_service.apply_asset_delta(
        db_session,
        student_id=two_lesson_chain.user.id,
        asset_id=two_lesson_chain.a_video.id,
        delta=AssetProgressDelta(watch_pct=0.3),
    )
    assert res.asset_progress.watch_pct == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_force_lesson_check_returns_blocking_reasons(
    db_session, two_lesson_chain
):
    completed, unlocked, missing = (
        await lesson_progress_service.force_lesson_check(
            db_session,
            student_id=two_lesson_chain.user.id,
            lesson_id=two_lesson_chain.a.id,
        )
    )
    assert completed is False
    assert unlocked == []
    assert missing  # at least one reason
