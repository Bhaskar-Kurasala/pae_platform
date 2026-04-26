"""Integration tests for the load_consistency UNION over three sources.

The original implementation only counted `agent_actions`. The Today refactor
unions in `student_progress.completed_at` and `exercise_submissions.created_at`
so a learner who watches videos and submits code without triggering an agent
no longer shows a false zero.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_action import AgentAction
from app.models.course import Course
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.lesson import Lesson
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.services.consistency_service import load_consistency


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, email: str = "c@test.dev") -> User:
    u = User(email=email, full_name="Consistency Tester", role="student")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_lesson(
    db: AsyncSession, *, course_slug: str = "c-1", lesson_slug: str = "l-1"
) -> Lesson:
    course = Course(
        title="C", slug=course_slug, description="d", difficulty="beginner"
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    lesson = Lesson(
        course_id=course.id,
        title="L",
        slug=lesson_slug,
        order=1,
        duration_seconds=60,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def _make_exercise(db: AsyncSession, lesson: Lesson) -> Exercise:
    ex = Exercise(
        lesson_id=lesson.id,
        title="E",
        description="d",
        difficulty="medium",
    )
    db.add(ex)
    await db.commit()
    await db.refresh(ex)
    return ex


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_consistency_returns_zero_for_inactive_user(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    days, window = await load_consistency(
        db_session,
        user_id=user.id,
        now=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
    )
    assert days == 0
    assert window == 7


@pytest.mark.asyncio
async def test_load_consistency_counts_completed_lessons(
    db_session: AsyncSession,
) -> None:
    """A user who only completes lessons (no agent actions) should still count."""
    user = await _make_user(db_session)
    lesson = await _make_lesson(db_session)
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    db_session.add(
        StudentProgress(
            student_id=user.id,
            lesson_id=lesson.id,
            status="completed",
            completed_at=now - timedelta(days=1),
        )
    )
    await db_session.commit()

    days, _ = await load_consistency(db_session, user_id=user.id, now=now)
    assert days == 1


@pytest.mark.asyncio
async def test_load_consistency_counts_exercise_submissions(
    db_session: AsyncSession,
) -> None:
    """Exercise submissions count even when the user never completed a lesson."""
    user = await _make_user(db_session)
    lesson = await _make_lesson(db_session)
    exercise = await _make_exercise(db_session, lesson)
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    sub = ExerciseSubmission(
        student_id=user.id,
        exercise_id=exercise.id,
        status="graded",
        score=85,
    )
    db_session.add(sub)
    await db_session.commit()
    # ExerciseSubmission.created_at is auto-populated; force into window.
    sub.created_at = now - timedelta(days=2)
    await db_session.commit()

    days, _ = await load_consistency(db_session, user_id=user.id, now=now)
    assert days == 1


@pytest.mark.asyncio
async def test_load_consistency_unions_all_three_sources_dedupes_same_day(
    db_session: AsyncSession,
) -> None:
    """An agent action + a lesson completion + a submission on the same day
    counts as ONE active day, not three."""
    user = await _make_user(db_session)
    lesson = await _make_lesson(db_session)
    exercise = await _make_exercise(db_session, lesson)
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    same_day = now - timedelta(hours=4)

    action = AgentAction(
        student_id=user.id,
        agent_name="socratic_tutor",
        action_type="chat",
        status="completed",
    )
    db_session.add(action)

    db_session.add(
        StudentProgress(
            student_id=user.id,
            lesson_id=lesson.id,
            status="completed",
            completed_at=same_day,
        )
    )
    sub = ExerciseSubmission(
        student_id=user.id,
        exercise_id=exercise.id,
        status="graded",
        score=80,
    )
    db_session.add(sub)
    await db_session.commit()
    action.created_at = same_day
    sub.created_at = same_day
    await db_session.commit()

    days, _ = await load_consistency(db_session, user_id=user.id, now=now)
    assert days == 1


@pytest.mark.asyncio
async def test_load_consistency_counts_distinct_days_across_sources(
    db_session: AsyncSession,
) -> None:
    """Three different sources on three different days → 3."""
    user = await _make_user(db_session)
    lesson = await _make_lesson(db_session)
    exercise = await _make_exercise(db_session, lesson)
    now = datetime(2026, 4, 25, 23, 0, tzinfo=UTC)

    # Day A: agent action only
    action = AgentAction(
        student_id=user.id,
        agent_name="socratic_tutor",
        action_type="chat",
        status="completed",
    )
    db_session.add(action)
    # Day B: lesson completion
    db_session.add(
        StudentProgress(
            student_id=user.id,
            lesson_id=lesson.id,
            status="completed",
            completed_at=now - timedelta(days=2),
        )
    )
    # Day C: submission
    sub = ExerciseSubmission(
        student_id=user.id,
        exercise_id=exercise.id,
        status="graded",
        score=70,
    )
    db_session.add(sub)
    await db_session.commit()
    action.created_at = now - timedelta(days=4)
    sub.created_at = now - timedelta(days=1)
    await db_session.commit()

    days, _ = await load_consistency(db_session, user_id=user.id, now=now)
    assert days == 3


@pytest.mark.asyncio
async def test_load_consistency_excludes_other_users(
    db_session: AsyncSession,
) -> None:
    me = await _make_user(db_session, "me@test.dev")
    other = await _make_user(db_session, "other@test.dev")
    lesson = await _make_lesson(db_session)
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    db_session.add(
        StudentProgress(
            student_id=other.id,
            lesson_id=lesson.id,
            status="completed",
            completed_at=now - timedelta(days=1),
        )
    )
    await db_session.commit()

    days, _ = await load_consistency(db_session, user_id=me.id, now=now)
    assert days == 0


@pytest.mark.asyncio
async def test_load_consistency_excludes_activity_outside_window(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    lesson = await _make_lesson(db_session)
    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    # 30 days back is well outside the 7-day window.
    db_session.add(
        StudentProgress(
            student_id=user.id,
            lesson_id=lesson.id,
            status="completed",
            completed_at=now - timedelta(days=30),
        )
    )
    await db_session.commit()

    days, _ = await load_consistency(db_session, user_id=user.id, now=now)
    assert days == 0
