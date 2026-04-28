"""Integration test for build_promotion_summary + confirm_promotion.

Covers:
  - rung derivation for a fresh user (everything locked or current)
  - rung derivation when foundation is met but lessons aren't done
  - rung derivation when all 4 rungs are met → gate flips to ready_to_promote
  - confirm_promotion sets users.promoted_at + promoted_to_role idempotently
  - confirm_promotion 409s (returns None) when gate isn't open
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.goal_contract import GoalContract
from app.models.interview_session import InterviewSession
from app.models.lesson import Lesson
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.services.promotion_summary_service import (
    REQUIRED_INTERVIEWS,
    _build_rungs,
    _motivation_to_role,
    build_promotion_summary,
    confirm_promotion,
)


# ---------------------------------------------------------------------------
# Pure rung builder
# ---------------------------------------------------------------------------


def test_build_rungs_all_locked_when_no_progress() -> None:
    rungs = _build_rungs(
        completed_lessons=0,
        total_lessons=10,
        capstone_subs=0,
        completed_interviews=0,
    )
    assert len(rungs) == 4
    assert rungs[0].state == "current"  # foundation always currently in flight
    assert rungs[1].state == "locked"
    assert rungs[2].state == "locked"
    assert rungs[3].state == "locked"


def test_build_rungs_foundation_done_unlocks_lessons_complete() -> None:
    rungs = _build_rungs(
        completed_lessons=5,
        total_lessons=10,
        capstone_subs=0,
        completed_interviews=0,
    )
    assert rungs[0].state == "done"
    assert rungs[1].state == "current"
    assert rungs[2].state == "locked"
    assert rungs[3].state == "locked"


def test_build_rungs_all_done_when_everything_met() -> None:
    rungs = _build_rungs(
        completed_lessons=10,
        total_lessons=10,
        capstone_subs=1,
        completed_interviews=REQUIRED_INTERVIEWS,
    )
    for r in rungs:
        assert r.state == "done"


def test_build_rungs_capstone_unlocks_interview_rung() -> None:
    rungs = _build_rungs(
        completed_lessons=10,
        total_lessons=10,
        capstone_subs=1,
        completed_interviews=0,
    )
    assert rungs[2].state == "done"
    assert rungs[3].state == "current"


def test_build_rungs_strict_ordering_capstone_locked_until_lessons_done() -> None:
    """A capstone submission counts only after lessons rung is done — keeps
    the ladder visual honest even if the student drafts a capstone early."""
    rungs = _build_rungs(
        completed_lessons=5,
        total_lessons=10,
        capstone_subs=1,  # Stamped early!
        completed_interviews=0,
    )
    # Lessons rung 2 is current; capstone shouldn't read as done yet.
    assert rungs[1].state == "current"
    assert rungs[2].state == "locked"
    assert rungs[3].state == "locked"


def test_build_rungs_strict_ordering_interviews_locked_until_capstone() -> None:
    """Same rule for the interview rung — even if 2 interviews are
    completed, it's locked until capstone has crossed."""
    rungs = _build_rungs(
        completed_lessons=10,
        total_lessons=10,
        capstone_subs=0,  # No capstone yet.
        completed_interviews=REQUIRED_INTERVIEWS,
    )
    assert rungs[1].state == "done"
    assert rungs[2].state == "current"  # Capstone is current.
    assert rungs[3].state == "locked"  # Interviews still locked.


def test_motivation_to_role_fallbacks() -> None:
    assert _motivation_to_role("career_switch") == ("Python Developer", "Data Analyst")
    assert _motivation_to_role("skill_up") == ("Engineer", "Senior Engineer")
    assert _motivation_to_role(None) == ("Python Developer", "Data Analyst")


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


async def _make_user(
    db: AsyncSession, *, email: str, full_name: str = "Tester"
) -> User:
    user = User(email=email, full_name=full_name, role="student")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_course_with_lessons(
    db: AsyncSession, *, title: str, lesson_count: int
) -> tuple[Course, list[Lesson]]:
    course = Course(
        title=title,
        slug=title.lower().replace(" ", "-"),
        description="",
        is_published=True,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    lessons = [
        Lesson(
            course_id=course.id,
            title=f"L{i}",
            slug=f"l{i}",
            order=i,
            duration_seconds=1800,
        )
        for i in range(1, lesson_count + 1)
    ]
    db.add_all(lessons)
    await db.commit()
    for lesson in lessons:
        await db.refresh(lesson)
    return course, lessons


@pytest.mark.asyncio
async def test_promotion_summary_fresh_user_not_ready(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, email="fresh@test.dev")
    summary = await build_promotion_summary(db_session, user=user)
    assert summary.gate_status == "not_ready"
    assert summary.promoted_at is None
    # Without enrollments the foundation rung is still current (default copy).
    assert summary.rungs[0].state == "current"


@pytest.mark.asyncio
async def test_promotion_summary_all_done_flips_to_ready(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    user = await _make_user(db_session, email="ready@test.dev")
    db_session.add(
        GoalContract(
            user_id=user.id,
            motivation="career_switch",
            deadline_months=6,
            success_statement="Land senior role.",
            target_role="Senior GenAI Engineer",
            created_at=now - timedelta(days=10),
            updated_at=now - timedelta(days=10),
        )
    )

    course, lessons = await _make_course_with_lessons(
        db_session, title="Foundations", lesson_count=4
    )
    db_session.add(
        Enrollment(
            student_id=user.id,
            course_id=course.id,
            status="active",
            enrolled_at=now - timedelta(days=10),
            progress_pct=100.0,
        )
    )
    for lesson in lessons:
        db_session.add(
            StudentProgress(
                student_id=user.id,
                lesson_id=lesson.id,
                status="completed",
                completed_at=now - timedelta(days=1),
            )
        )

    capstone = Exercise(
        lesson_id=lessons[-1].id,
        title="Capstone",
        is_capstone=True,
        pass_score=80,
        points=100,
    )
    db_session.add(capstone)
    await db_session.commit()
    await db_session.refresh(capstone)
    db_session.add(
        ExerciseSubmission(
            student_id=user.id,
            exercise_id=capstone.id,
            status="graded",
            score=85,
            code="ok",
        )
    )
    for i in range(REQUIRED_INTERVIEWS):
        db_session.add(
            InterviewSession(
                user_id=user.id,
                mode="behavioral",
                status="completed",
                created_at=now - timedelta(days=i + 1),
            )
        )
    await db_session.commit()
    await db_session.refresh(user)

    summary = await build_promotion_summary(db_session, user=user)
    assert summary.gate_status == "ready_to_promote"
    assert summary.role.to_role == "Senior GenAI Engineer"
    for rung in summary.rungs:
        assert rung.state == "done"
    assert summary.stats.completed_lessons == 4
    assert summary.stats.capstone_submissions == 1
    assert summary.stats.completed_interviews == REQUIRED_INTERVIEWS


@pytest.mark.asyncio
async def test_confirm_promotion_returns_none_when_gate_locked(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, email="locked@test.dev")
    result = await confirm_promotion(db_session, user=user)
    assert result is None


@pytest.mark.asyncio
async def test_confirm_promotion_is_idempotent(
    db_session: AsyncSession,
) -> None:
    """Once promoted_at is set, a second call returns the existing record
    instead of stamping a new timestamp."""
    user = await _make_user(db_session, email="idem@test.dev")
    user.promoted_at = datetime.now(UTC) - timedelta(days=2)
    user.promoted_to_role = "Data Analyst"
    await db_session.commit()
    await db_session.refresh(user)

    first = await confirm_promotion(db_session, user=user)
    assert first is not None
    second = await confirm_promotion(db_session, user=user)
    assert second is not None
    assert first.promoted_at == second.promoted_at
    assert first.promoted_to_role == "Data Analyst"
