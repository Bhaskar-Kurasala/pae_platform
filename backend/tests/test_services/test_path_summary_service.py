"""Integration test for build_path_summary — the Path aggregator.

Asserts the constellation, ladder lessons + labs, proof wall, and overall
progress all derive from real DB rows. Pure helpers are tested separately.
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
from app.models.lesson import Lesson
from app.models.skill import Skill
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.models.user_skill_state import UserSkillState
from app.services.path_summary_service import (
    _duration_minutes_for_exercise,
    _duration_minutes_for_lesson,
    _mastery_to_state,
    _split_label,
    _truncate_goal,
    build_path_summary,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_split_label_two_words() -> None:
    assert _split_label("Data Analyst") == "Data\nAnalyst"


def test_split_label_one_word() -> None:
    assert _split_label("Python") == "Python"


def test_split_label_three_words_splits_at_midpoint() -> None:
    # 3 words → first 2 / last 1
    assert _split_label("Senior GenAI Engineer") == "Senior GenAI\nEngineer"


def test_truncate_goal_caps_at_three_words() -> None:
    out = _truncate_goal("ship one async client today and grade it")
    assert out.count("\n") == 1
    # First three words preserved (then split mid-way), later words dropped.
    assert "ship" in out and "async" in out
    assert "grade" not in out


def test_mastery_to_state_mapping() -> None:
    assert _mastery_to_state("mastered") == "done"
    assert _mastery_to_state("proficient") == "current"
    assert _mastery_to_state("novice") == "upcoming"
    assert _mastery_to_state(None) == "upcoming"


def test_duration_minutes_for_lesson_uses_seconds() -> None:
    lesson = Lesson(
        course_id=None,  # type: ignore[arg-type]
        title="t",
        slug="t",
        order=0,
        duration_seconds=2700,  # 45 min
    )
    assert _duration_minutes_for_lesson(lesson) == 45


def test_duration_minutes_for_lesson_falls_back_to_30() -> None:
    lesson = Lesson(
        course_id=None,  # type: ignore[arg-type]
        title="t",
        slug="t",
        order=0,
        duration_seconds=0,
    )
    assert _duration_minutes_for_lesson(lesson) == 30


def test_duration_minutes_for_exercise_caps_at_60() -> None:
    ex = Exercise(
        lesson_id=None,  # type: ignore[arg-type]
        title="t",
        points=500,  # would be 250 min uncapped
    )
    assert _duration_minutes_for_exercise(ex) == 60


def test_duration_minutes_for_exercise_floor_at_10() -> None:
    ex = Exercise(
        lesson_id=None,  # type: ignore[arg-type]
        title="t",
        points=4,
    )
    assert _duration_minutes_for_exercise(ex) == 10


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_summary_returns_full_payload(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)

    user = User(
        email="path@test.dev",
        full_name="Priya Kumar",
        role="student",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    contract = GoalContract(
        user_id=user.id,
        motivation="career_switch",
        deadline_months=6,
        success_statement="I will land a senior GenAI role.",
        target_role="Senior GenAI Engineer",
        created_at=now - timedelta(days=5),
        updated_at=now - timedelta(days=5),
    )
    db_session.add(contract)

    skill_a = Skill(
        slug="python-foundations",
        name="Python Foundations",
        description="Functions, modules, async.",
        difficulty=1,
    )
    skill_b = Skill(
        slug="rag-basics",
        name="RAG Basics",
        description="Hybrid retrieval + generation.",
        difficulty=2,
    )
    db_session.add_all([skill_a, skill_b])
    await db_session.commit()
    await db_session.refresh(skill_a)
    await db_session.refresh(skill_b)
    db_session.add(
        UserSkillState(
            user_id=user.id,
            skill_id=skill_a.id,
            mastery_level="mastered",
            confidence=0.9,
            last_touched_at=now - timedelta(hours=3),
        )
    )

    course = Course(
        title="Python Foundations",
        slug="python-foundations-course",
        description="Solidify the role.",
        difficulty="beginner",
        is_published=True,
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)
    lesson1 = Lesson(
        course_id=course.id,
        title="Python fundamentals",
        slug="l1",
        order=1,
        duration_seconds=2700,  # 45 min
    )
    lesson2 = Lesson(
        course_id=course.id,
        title="OOP and modules",
        slug="l2",
        order=2,
        duration_seconds=3000,
    )
    db_session.add_all([lesson1, lesson2])
    await db_session.commit()
    await db_session.refresh(lesson1)
    await db_session.refresh(lesson2)

    enrollment = Enrollment(
        student_id=user.id,
        course_id=course.id,
        status="active",
        enrolled_at=now - timedelta(days=5),
        progress_pct=0.0,
    )
    db_session.add(enrollment)
    db_session.add(
        StudentProgress(
            student_id=user.id,
            lesson_id=lesson1.id,
            status="completed",
            completed_at=now - timedelta(days=1),
        )
    )

    # Two labs on lesson2 — one already done (failed status excluded).
    lab_a = Exercise(
        lesson_id=lesson2.id,
        title="Lab A · Retry with backoff",
        description="Retry a flaky API.",
        points=50,
        order=1,
    )
    lab_b = Exercise(
        lesson_id=lesson2.id,
        title="Lab B · Rate-limit queue",
        description="Throttle requests.",
        points=80,
        order=2,
    )
    db_session.add_all([lab_a, lab_b])
    await db_session.commit()
    await db_session.refresh(lab_a)
    await db_session.refresh(lab_b)
    db_session.add(
        ExerciseSubmission(
            student_id=user.id,
            exercise_id=lab_a.id,
            status="graded",
            score=85,
            code="def retry(): pass",
        )
    )

    # Up-sell course (not enrolled).
    upsell = Course(
        title="Data Analyst Path",
        slug="data-analyst-path",
        description="SQL + pandas.",
        difficulty="intermediate",
        price_cents=8900,
        is_published=True,
    )
    db_session.add(upsell)
    await db_session.commit()

    # Peer with shared submission for proof wall.
    peer = User(email="peer@test.dev", full_name="Ada Lovelace", role="student")
    db_session.add(peer)
    await db_session.commit()
    await db_session.refresh(peer)
    peer_lab = Exercise(lesson_id=lesson2.id, title="Peer lab", points=40, order=3)
    db_session.add(peer_lab)
    await db_session.commit()
    await db_session.refresh(peer_lab)
    db_session.add(
        ExerciseSubmission(
            student_id=peer.id,
            exercise_id=peer_lab.id,
            status="graded",
            score=91,
            code="async def ask():\n    return 1",
            shared_with_peers=True,
        )
    )
    await db_session.commit()

    summary = await build_path_summary(db_session, user=user)

    # Constellation: 5 ordered skill stars + 1 goal star = 6 total.
    assert len(summary.constellation) == 6
    assert summary.constellation[-1].state == "goal"
    # First star reflects mastered Python Foundations.
    assert summary.constellation[0].state == "done"
    # Goal star pulls from goal contract's target_role.
    assert "Senior" in summary.constellation[-1].label

    # Levels: current course + upsell + goal rung.
    assert len(summary.levels) == 3
    current = summary.levels[0]
    assert current.title == "Python Foundations"
    assert current.state == "current"
    assert any(l_.title == "Python fundamentals" for l_ in current.lessons)
    # Lesson 2 is "current" because lesson 1 is done.
    second = next(l_ for l_ in current.lessons if l_.title == "OOP and modules")
    assert second.status == "current"
    # Lesson 2 has 3 labs (lab_a done, lab_b current, peer_lab locked).
    assert len(second.labs) == 3
    assert second.labs[0].status == "done"
    assert second.labs_completed == 1

    # Up-sell rung surfaces Data Analyst Path with the price.
    upsell_level = summary.levels[1]
    assert upsell_level.title == "Data Analyst Path"
    assert upsell_level.unlock_price_cents == 8900

    # Goal rung uses target_role copy.
    assert summary.levels[2].state == "goal"
    assert "Senior" in summary.levels[2].title

    # Proof wall surfaces the peer's shared submission.
    assert len(summary.proof_wall) == 1
    assert summary.proof_wall[0].author_name == "Ada Lovelace"
    assert summary.proof_wall[0].score == 91


@pytest.mark.asyncio
async def test_path_summary_empty_user_uses_editorial_fallbacks(
    db_session: AsyncSession,
) -> None:
    """A brand-new user with no enrollments / no goal still returns a
    well-formed payload — the constellation falls back to the default role
    ladder and the levels list is just the goal rung."""
    user = User(email="empty@test.dev", full_name="New", role="student")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    summary = await build_path_summary(db_session, user=user)

    assert len(summary.constellation) == 6
    assert summary.constellation[-1].state == "goal"
    # No active course → only the goal rung.
    assert len(summary.levels) >= 1
    assert summary.levels[-1].state == "goal"
    assert summary.proof_wall == []
