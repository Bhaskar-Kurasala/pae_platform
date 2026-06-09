"""Integration test for build_today_summary — the Today aggregator.

Seeds a realistic-ish user state (goal, enrollment, progress, SRS card,
capstone, micro-win source, cohort event) and asserts every top-level field
on TodaySummaryResponse is populated correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cohort_event import CohortEvent
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.goal_contract import GoalContract
from app.models.lesson import Lesson
from app.models.skill import Skill
from app.models.srs_card import SRSCard
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.models.user_skill_state import UserSkillState
from app.services.today_summary_service import (
    _first_name,
    build_today_summary,
)


# ---------------------------------------------------------------------------
# _first_name (pure)
# ---------------------------------------------------------------------------


def test_first_name_picks_first_token() -> None:
    u = User(email="x@y", full_name="Priya Kumar Singh", role="student")
    assert _first_name(u) == "Priya"


def test_first_name_handles_missing_name() -> None:
    u = User(email="x@y", full_name="", role="student")
    assert _first_name(u) == ""


def test_first_name_strips_whitespace() -> None:
    u = User(email="x@y", full_name="   Cher   ", role="student")
    assert _first_name(u) == "Cher"


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


async def _seed_world(
    db: AsyncSession, *, now: datetime
) -> tuple[User, Course, Lesson, Lesson, Exercise]:
    """Build a populated world for the aggregator and return the principal user.

    Returns: user, course, lesson1, lesson2, capstone exercise
    """
    user = User(
        email="today@test.dev", full_name="Priya Kumar", role="student"
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Goal contract — 6 months ahead. Explicit created_at so days_remaining
    # is deterministic regardless of wall-clock skew between server defaults
    # and our pinned `now`.
    contract = GoalContract(
        user_id=user.id,
        motivation="career_switch",
        deadline_months=6,
        success_statement="I will land a Python Developer role.",
        weekly_hours="6-10",
        target_role="Python Developer",
        created_at=now - timedelta(days=10),
        updated_at=now - timedelta(days=10),
    )
    db.add(contract)

    # Course with 2 lessons; one completed.
    course = Course(
        title="Foundations",
        slug="foundations",
        description="d",
        difficulty="beginner",
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    lesson1 = Lesson(
        course_id=course.id,
        title="L1",
        slug="l1",
        order=1,
        duration_seconds=60,
    )
    lesson2 = Lesson(
        course_id=course.id,
        title="L2",
        slug="l2",
        order=2,
        duration_seconds=60,
    )
    db.add_all([lesson1, lesson2])
    await db.commit()
    await db.refresh(lesson1)
    await db.refresh(lesson2)

    enrollment = Enrollment(
        student_id=user.id,
        course_id=course.id,
        status="active",
        enrolled_at=now - timedelta(days=10),
        progress_pct=0.0,
    )
    db.add(enrollment)
    db.add(
        StudentProgress(
            student_id=user.id,
            lesson_id=lesson1.id,
            status="completed",
            completed_at=now - timedelta(hours=12),
        )
    )

    # Skill + UserSkillState (recently touched) — drives current_focus.
    skill = Skill(
        slug="rag",
        name="Retrieval-Augmented Generation",
        description="Hybrid retrieval + generation",
        difficulty=2,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    db.add(
        UserSkillState(
            user_id=user.id,
            skill_id=skill.id,
            mastery_level="practicing",
            confidence=0.5,
            last_touched_at=now - timedelta(hours=2),
        )
    )

    # Capstone exercise + a draft submission.
    capstone = Exercise(
        lesson_id=lesson2.id,
        title="Capstone Build",
        description="Ship a thing",
        difficulty="hard",
        is_capstone=True,
        pass_score=80,
        due_at=now + timedelta(days=14),
    )
    db.add(capstone)
    await db.commit()
    await db.refresh(capstone)
    db.add(
        ExerciseSubmission(
            student_id=user.id,
            exercise_id=capstone.id,
            status="graded",
            score=72,
            code="print('hi')",
        )
    )

    # SRS card due now.
    db.add(
        SRSCard(
            user_id=user.id,
            concept_key="lesson:l1",
            prompt="What is L1?",
            answer="It's L1",
            hint="Think hard",
            next_due_at=now - timedelta(minutes=5),
        )
    )

    # Cohort event from a peer.
    peer = User(email="peer@test.dev", full_name="Ada Lovelace", role="student")
    db.add(peer)
    await db.commit()
    await db.refresh(peer)
    db.add(
        CohortEvent(
            kind="level_up",
            actor_id=peer.id,
            actor_handle="Ada L.",
            label="reached Python Developer",
            occurred_at=now - timedelta(hours=4),
            level_slug="python_developer",
        )
    )

    await db.commit()
    return user, course, lesson1, lesson2, capstone


@pytest.mark.asyncio
async def test_build_today_summary_populates_every_top_level_field(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 4, 25, 14, 0, tzinfo=UTC)
    user, course, lesson1, lesson2, capstone = await _seed_world(
        db_session, now=now
    )

    summary = await build_today_summary(db_session, user=user, now=now)

    # User
    assert summary.user.first_name == "Priya"

    # Goal
    assert summary.goal.success_statement == "I will land a Python Developer role."
    assert summary.goal.target_role == "Python Developer"
    assert summary.goal.motivation == "career_switch"
    # Created 10 days before `now`, 6-month deadline (180 days) → 170 left.
    assert summary.goal.days_remaining == 170

    # Consistency — at least one active day from the lesson completion.
    assert summary.consistency.window_days == 7
    assert summary.consistency.days_active >= 1

    # Progress — 1 of 2 lessons done = 50% weighted.
    assert summary.progress.lessons_total == 2
    assert summary.progress.lessons_completed_total == 1
    assert summary.progress.overall_percentage == 50.0
    assert summary.progress.active_course_id == course.id
    assert summary.progress.active_course_title == "Foundations"
    assert summary.progress.next_lesson_id == lesson2.id
    assert summary.progress.next_lesson_title == "L2"
    # tiny course → today_unlock capped at 25
    assert summary.progress.today_unlock_percentage == 25.0

    # Session — read-only on GET aggregator. No row is opened until the user
    # calls mark_step. Ordinal is projected as 1 because no prior session.
    assert summary.session.id is None
    assert summary.session.ordinal == 1
    assert summary.session.started_at is None
    assert summary.session.warmup_done_at is None

    # Current focus — most recently touched skill.
    assert summary.current_focus.skill_slug == "rag"
    assert summary.current_focus.skill_name == "Retrieval-Augmented Generation"
    assert "retrieval" in (summary.current_focus.skill_blurb or "").lower()

    # Capstone — earliest due, with the user's draft.
    assert summary.capstone.exercise_id == capstone.id
    assert summary.capstone.title == "Capstone Build"
    assert summary.capstone.drafts_count == 1
    assert summary.capstone.draft_quality == 72
    assert summary.capstone.days_to_due is not None
    assert 0 <= summary.capstone.days_to_due <= 14

    # Milestone — derived from goal.
    assert summary.next_milestone.label == "Python Developer"
    assert summary.next_milestone.days == summary.goal.days_remaining

    # Readiness — best-effort, may be zero in tests.
    assert summary.readiness.current >= 0
    assert isinstance(summary.readiness.delta_week, int)

    # Intention — none set.
    assert summary.intention.text is None

    # Due card count — 1 SRS card past next_due_at.
    assert summary.due_card_count == 1

    # Cohort signals.
    assert summary.peers_at_level == 1  # the seeded peer
    assert summary.promotions_today == 1  # one level_up in the last 24h

    # Cohort feed surfaces the level_up event.
    assert len(summary.cohort_events) == 1
    assert summary.cohort_events[0].kind == "level_up"
    assert summary.cohort_events[0].actor_handle == "Ada L."

    # Micro-wins — one lesson completion within 48h.
    assert any(w.kind == "lesson_completed" for w in summary.micro_wins)


@pytest.mark.asyncio
async def test_build_today_summary_for_blank_user_has_safe_defaults(
    db_session: AsyncSession,
) -> None:
    user = User(email="blank@test.dev", full_name="Blank", role="student")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    summary = await build_today_summary(db_session, user=user, now=now)

    assert summary.user.first_name == "Blank"
    assert summary.goal.success_statement is None
    assert summary.goal.days_remaining == 0
    assert summary.consistency.days_active == 0
    assert summary.progress.lessons_total == 0
    assert summary.progress.overall_percentage == 0.0
    assert summary.progress.active_course_id is None
    # GET is read-only — projects ordinal=1 without writing.
    assert summary.session.ordinal == 1
    assert summary.session.id is None
    assert summary.current_focus.skill_slug is None
    assert summary.capstone.exercise_id is None
    assert summary.due_card_count == 0
    assert summary.peers_at_level == 0
    assert summary.promotions_today == 0
    assert summary.micro_wins == []
    assert summary.cohort_events == []
    # Milestone label falls back to "your next role" when nothing's set.
    assert summary.next_milestone.label == "your next role"
