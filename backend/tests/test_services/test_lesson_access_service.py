"""Unit tests for the lesson player access + completion logic.

Pure-function tests for evaluate_lesson_completion (no DB needed) and
DB-backed tests for the prerequisite walker + course-state builder.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models.lesson import Lesson
from app.models.lesson_asset import (
    ASSET_KIND_LEARNING_NOTEBOOK,
    ASSET_KIND_PRACTICE_NOTEBOOK,
    ASSET_KIND_VIDEO,
    LessonAsset,
)
from app.models.lesson_prerequisite import LessonPrerequisite
from app.models.student_asset_progress import StudentAssetProgress
from app.services import lesson_access_service


# ---------------------------------------------------------------------------
# Pure-function: evaluate_lesson_completion
# ---------------------------------------------------------------------------


def _lesson(**overrides):
    base = {
        "id": uuid.uuid4(),
        "course_id": uuid.uuid4(),
        "title": "Lesson",
        "slug": "lesson",
        "order": 0,
        "completion_policy": None,
        "metadata_": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _asset(kind, *, order=0, title="Asset"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        kind=kind,
        order=order,
        title=title,
        description=None,
        duration_seconds=None,
    )


def _progress(asset_id, *, watch_pct=0.0, executed=False, completed=False):
    return SimpleNamespace(
        id=uuid.uuid4(),
        asset_id=asset_id,
        student_id=uuid.uuid4(),
        status="completed" if completed else "not_started",
        watch_pct=watch_pct,
        watched_seconds=int(watch_pct * 100),
        last_position_seconds=0,
        execution_count=1 if executed else 0,
        executed_at=datetime.now(UTC) if executed else None,
        completed_at=datetime.now(UTC) if completed else None,
    )


def test_default_policy_requires_video_and_notebook_runs():
    lesson = _lesson()
    video = _asset(ASSET_KIND_VIDEO, title="Intro")
    learning = _asset(ASSET_KIND_LEARNING_NOTEBOOK, title="Read")
    practice = _asset(ASSET_KIND_PRACTICE_NOTEBOOK, title="Practice 1")

    # Nothing done → not complete, all 3 missing.
    res = lesson_access_service.evaluate_lesson_completion(
        lesson=lesson,
        assets=[video, learning, practice],
        progress_by_asset={},
    )
    assert res.is_complete is False
    assert res.completion_pct == 0.0
    assert len(res.missing_reasons) == 3


def test_completion_with_all_gates_satisfied():
    lesson = _lesson()
    video = _asset(ASSET_KIND_VIDEO, title="Intro")
    learning = _asset(ASSET_KIND_LEARNING_NOTEBOOK)
    practice = _asset(ASSET_KIND_PRACTICE_NOTEBOOK)

    progress = {
        video.id: _progress(video.id, watch_pct=0.95),
        learning.id: _progress(learning.id, executed=True),
        practice.id: _progress(practice.id, executed=True),
    }
    res = lesson_access_service.evaluate_lesson_completion(
        lesson=lesson,
        assets=[video, learning, practice],
        progress_by_asset=progress,
    )
    assert res.is_complete is True
    assert res.completion_pct == 1.0
    assert res.missing_reasons == []


def test_video_below_threshold_blocks_completion():
    lesson = _lesson()
    video = _asset(ASSET_KIND_VIDEO, title="Intro")
    learning = _asset(ASSET_KIND_LEARNING_NOTEBOOK)

    progress = {
        video.id: _progress(video.id, watch_pct=0.5),
        learning.id: _progress(learning.id, executed=True),
    }
    res = lesson_access_service.evaluate_lesson_completion(
        lesson=lesson, assets=[video, learning], progress_by_asset=progress
    )
    assert res.is_complete is False
    assert any("90%" in m for m in res.missing_reasons)


def test_custom_policy_lowers_video_threshold():
    lesson = _lesson(completion_policy={"video_min_watch_pct": 0.5})
    video = _asset(ASSET_KIND_VIDEO, title="Intro")
    progress = {video.id: _progress(video.id, watch_pct=0.55)}

    res = lesson_access_service.evaluate_lesson_completion(
        lesson=lesson, assets=[video], progress_by_asset=progress
    )
    assert res.is_complete is True


def test_completion_pct_partial():
    lesson = _lesson()
    video = _asset(ASSET_KIND_VIDEO)
    practice = _asset(ASSET_KIND_PRACTICE_NOTEBOOK)
    progress = {video.id: _progress(video.id, watch_pct=0.95)}

    res = lesson_access_service.evaluate_lesson_completion(
        lesson=lesson, assets=[video, practice], progress_by_asset=progress
    )
    assert res.is_complete is False
    assert res.completion_pct == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Prereq walker
# ---------------------------------------------------------------------------


def test_all_prereqs_walks_transitively():
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    edges = {b: [a], c: [b], d: [c]}
    assert lesson_access_service.all_prereqs(edges, d) == {a, b, c}
    assert lesson_access_service.all_prereqs(edges, b) == {a}
    assert lesson_access_service.all_prereqs(edges, a) == set()


def test_all_prereqs_breaks_cycles_safely():
    a, b = uuid.uuid4(), uuid.uuid4()
    # Cycle: a → b → a (would never be persisted, but defensive).
    edges = {a: [b], b: [a]}
    out = lesson_access_service.all_prereqs(edges, a)
    # Both nodes are reachable; the walker must not loop forever.
    assert out == {a, b}


# ---------------------------------------------------------------------------
# DB-backed: build_course_state
# ---------------------------------------------------------------------------


@pytest.fixture
async def seeded_course(db_session):
    """Seed a tiny 2-lesson course with one prereq edge.

    Lesson A — video + notebook (no prereqs). Unlocked.
    Lesson B — video only, requires A.
    """
    from app.models.course import Course
    from app.models.user import User

    user = User(
        email=f"learn-{uuid.uuid4().hex[:8]}@test.dev",
        hashed_password="x",
        role="student",
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    course = Course(
        title="Course",
        slug=f"c-{uuid.uuid4().hex[:8]}",
        description="d",
        difficulty="beginner",
        price_cents=0,
        is_published=True,
    )
    db_session.add(course)
    await db_session.flush()

    lesson_a = Lesson(
        course_id=course.id,
        title="Lesson A",
        slug="a",
        order=0,
        is_published=True,
        duration_seconds=600,
    )
    lesson_b = Lesson(
        course_id=course.id,
        title="Lesson B",
        slug="b",
        order=1,
        is_published=True,
        duration_seconds=600,
    )
    db_session.add_all([lesson_a, lesson_b])
    await db_session.flush()

    a_video = LessonAsset(
        lesson_id=lesson_a.id,
        kind=ASSET_KIND_VIDEO,
        order=0,
        title="A intro video",
        storage_ref="playback_aaa",
    )
    a_nb = LessonAsset(
        lesson_id=lesson_a.id,
        kind=ASSET_KIND_LEARNING_NOTEBOOK,
        order=1,
        title="A notebook",
        storage_ref="courses/x/a.ipynb",
    )
    b_video = LessonAsset(
        lesson_id=lesson_b.id,
        kind=ASSET_KIND_VIDEO,
        order=0,
        title="B intro video",
        storage_ref="playback_bbb",
    )
    db_session.add_all([a_video, a_nb, b_video])
    await db_session.flush()

    db_session.add(
        LessonPrerequisite(
            lesson_id=lesson_b.id, requires_lesson_id=lesson_a.id
        )
    )
    await db_session.flush()

    return SimpleNamespace(
        user=user,
        course=course,
        lesson_a=lesson_a,
        lesson_b=lesson_b,
        a_video=a_video,
        a_nb=a_nb,
        b_video=b_video,
    )


@pytest.mark.asyncio
async def test_build_course_state_initial_lock(db_session, seeded_course):
    states = await lesson_access_service.build_course_state(
        db_session,
        student_id=seeded_course.user.id,
        course_id=seeded_course.course.id,
    )
    assert [s.lock_state for s in states] == ["unlocked", "locked"]
    assert "prerequisite" in (states[1].locked_reason or "").lower()


@pytest.mark.asyncio
async def test_completing_lesson_a_unlocks_lesson_b(db_session, seeded_course):
    # Mark A's video watched and notebook executed.
    db_session.add_all(
        [
            StudentAssetProgress(
                student_id=seeded_course.user.id,
                asset_id=seeded_course.a_video.id,
                status="completed",
                watch_pct=0.99,
                watched_seconds=600,
                completed_at=datetime.now(UTC),
            ),
            StudentAssetProgress(
                student_id=seeded_course.user.id,
                asset_id=seeded_course.a_nb.id,
                status="completed",
                executed_at=datetime.now(UTC),
                execution_count=1,
                completed_at=datetime.now(UTC),
            ),
        ]
    )
    await db_session.flush()

    states = await lesson_access_service.build_course_state(
        db_session,
        student_id=seeded_course.user.id,
        course_id=seeded_course.course.id,
    )
    by_id = {s.lesson.id: s for s in states}
    assert by_id[seeded_course.lesson_a.id].lock_state == "completed"
    assert by_id[seeded_course.lesson_b.id].lock_state == "unlocked"
