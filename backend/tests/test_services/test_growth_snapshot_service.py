"""Unit tests for growth snapshot service (P1-C-2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.models.user_skill_state import UserSkillState
from app.services.growth_snapshot_service import (
    build_and_persist,
    compute_snapshot,
    last_week_window,
    upsert_snapshot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, email: str = "s@t.test") -> User:
    u = User(email=email, full_name="Test", role="student")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_skill(db: AsyncSession, name: str, slug: str) -> Skill:
    from app.models.skill import Skill as _Skill  # avoid mypy false positive

    s = _Skill(name=name, slug=slug, description="d", difficulty=1)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# last_week_window
# ---------------------------------------------------------------------------


def test_last_week_window_on_monday() -> None:
    """Monday: week_ending is yesterday (Sunday); window is prior Mon–Sun."""
    monday = datetime(2026, 4, 13, 10, 0, tzinfo=UTC)  # Mon
    start, end, week_ending = last_week_window(monday)
    assert week_ending.isoformat() == "2026-04-12"  # Sunday
    assert start.isoformat() == "2026-04-06T00:00:00+00:00"  # Mon prior
    assert end.isoformat() == "2026-04-13T00:00:00+00:00"  # next Mon


def test_last_week_window_on_sunday() -> None:
    """Sunday: the *just-ended* week is the prior Mon–Sun (Sunday is mid-current-week).

    The beat job runs at Sunday 00:00 UTC, so at that moment we want the week
    that closed the day before — not the same-date Sunday.
    """
    sunday = datetime(2026, 4, 19, 0, 0, tzinfo=UTC)  # Sun 00:00
    _, _, week_ending = last_week_window(sunday)
    assert week_ending.isoformat() == "2026-04-12"


def test_last_week_window_midweek() -> None:
    """Wednesday: week_ending is the most recent Sunday."""
    wed = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)  # Wed
    _, _, week_ending = last_week_window(wed)
    assert week_ending.isoformat() == "2026-04-12"


# ---------------------------------------------------------------------------
# compute_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_snapshot_empty_user(db_session: AsyncSession) -> None:
    """A user with no activity gets a zeroed snapshot."""
    user = await _make_user(db_session)
    now = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)  # Wed

    stats = await compute_snapshot(db_session, user.id, now=now)

    assert stats.user_id == user.id
    assert stats.week_ending.isoformat() == "2026-04-12"
    assert stats.lessons_completed == 0
    assert stats.skills_touched == 0
    assert stats.streak_days == 0
    assert stats.top_concept is None
    assert stats.payload["quiz_attempts"] == 0
    assert stats.payload["reflections"] == 0


@pytest.mark.asyncio
async def test_compute_snapshot_counts_in_window_skills(
    db_session: AsyncSession,
) -> None:
    """Only skills touched inside Mon–Sun count; top_concept is highest-confidence."""
    user = await _make_user(db_session)
    skill_hi = await _make_skill(db_session, "Transformers", "transformers")
    skill_lo = await _make_skill(db_session, "Tokenizers", "tokenizers")

    # Window: 2026-04-06 Mon through 2026-04-12 Sun (end is 04-13 00:00 UTC)
    in_window = datetime(2026, 4, 9, 10, 0, tzinfo=UTC)  # Thu
    out_of_window = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)  # prior week

    db_session.add_all(
        [
            UserSkillState(
                user_id=user.id,
                skill_id=skill_hi.id,
                confidence=0.9,
                last_touched_at=in_window,
            ),
            UserSkillState(
                user_id=user.id,
                skill_id=skill_lo.id,
                confidence=0.3,
                last_touched_at=in_window,
            ),
            # out-of-window skill should not count
            UserSkillState(
                user_id=user.id,
                skill_id=(await _make_skill(db_session, "Old", "old")).id,
                confidence=0.99,
                last_touched_at=out_of_window,
            ),
        ]
    )
    await db_session.commit()

    now = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    stats = await compute_snapshot(db_session, user.id, now=now)

    assert stats.skills_touched == 2
    assert stats.top_concept == "Transformers"  # higher confidence


# ---------------------------------------------------------------------------
# upsert_snapshot — idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_is_idempotent(db_session: AsyncSession) -> None:
    """Running the snapshot twice for the same (user, week) upserts, not duplicates."""
    user = await _make_user(db_session)
    now = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)

    snap1 = await build_and_persist(db_session, user.id, now=now)
    snap2 = await build_and_persist(db_session, user.id, now=now)

    # Same row, not a duplicate
    assert snap1.id == snap2.id
    assert snap1.week_ending == snap2.week_ending

    from sqlalchemy import func, select

    from app.models.growth_snapshot import GrowthSnapshot

    count = (
        await db_session.execute(
            select(func.count(GrowthSnapshot.id)).where(
                GrowthSnapshot.user_id == user.id
            )
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_upsert_updates_changed_fields(db_session: AsyncSession) -> None:
    """Re-running with different computed stats updates the existing row."""
    user = await _make_user(db_session)
    now = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)

    # First run — empty state, gives 0 lessons.
    first = await build_and_persist(db_session, user.id, now=now)
    assert first.lessons_completed == 0

    # Hand-craft new stats with a higher count and upsert again.
    from app.services.growth_snapshot_service import SnapshotStats

    new_stats = SnapshotStats(
        user_id=user.id,
        week_ending=first.week_ending,
        lessons_completed=5,
        skills_touched=3,
        streak_days=2,
        top_concept="Attention",
        payload={"quiz_attempts": 1},
    )
    updated = await upsert_snapshot(db_session, new_stats)

    assert updated.id == first.id  # same row
    assert updated.lessons_completed == 5
    assert updated.skills_touched == 3
    assert updated.top_concept == "Attention"


# ---------------------------------------------------------------------------
# streak days
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streak_days_consecutive(db_session: AsyncSession) -> None:
    """Three consecutive days of activity ending today → streak=3."""
    user = await _make_user(db_session)
    skill = await _make_skill(db_session, "Attention", "attention")
    now = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)  # Wed

    # One UserSkillState can only hold the most recent touch, so use
    # three skills to simulate three distinct days.
    skill2 = await _make_skill(db_session, "Embeddings", "embeddings")
    skill3 = await _make_skill(db_session, "Softmax", "softmax")

    db_session.add_all(
        [
            UserSkillState(
                user_id=user.id, skill_id=skill.id, confidence=0.5,
                last_touched_at=now,
            ),
            UserSkillState(
                user_id=user.id, skill_id=skill2.id, confidence=0.5,
                last_touched_at=now - timedelta(days=1),
            ),
            UserSkillState(
                user_id=user.id, skill_id=skill3.id, confidence=0.5,
                last_touched_at=now - timedelta(days=2),
            ),
        ]
    )
    await db_session.commit()

    stats = await compute_snapshot(db_session, user.id, now=now)
    assert stats.streak_days == 3


@pytest.mark.asyncio
async def test_streak_days_breaks_on_gap(db_session: AsyncSession) -> None:
    """A day with no activity breaks the streak."""
    user = await _make_user(db_session)
    skill = await _make_skill(db_session, "A", "a")
    skill2 = await _make_skill(db_session, "B", "b")
    now = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)

    db_session.add_all(
        [
            UserSkillState(
                user_id=user.id, skill_id=skill.id, confidence=0.5,
                last_touched_at=now,  # today
            ),
            UserSkillState(
                user_id=user.id, skill_id=skill2.id, confidence=0.5,
                last_touched_at=now - timedelta(days=3),  # 3 days ago
            ),
        ]
    )
    await db_session.commit()

    stats = await compute_snapshot(db_session, user.id, now=now)
    assert stats.streak_days == 1  # today only


# ---------------------------------------------------------------------------
# lessons_completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lessons_completed_in_window(db_session: AsyncSession) -> None:
    """Only lessons completed inside the Mon–Sun window count."""
    user = await _make_user(db_session)
    # Need a lesson row to FK against; since lesson FK cascades, we must create one.
    from app.models.course import Course
    from app.models.lesson import Lesson

    course = Course(title="C", slug="c", description="d", difficulty="beginner")
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)

    lesson = Lesson(
        course_id=course.id, title="L1", slug="l1", order=1,
        youtube_video_id="x", duration_seconds=60,
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    # Window (from a Wed ref): 2026-04-06..2026-04-13
    in_window = datetime(2026, 4, 9, 10, 0, tzinfo=UTC)
    out_of_window = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    db_session.add_all(
        [
            StudentProgress(
                student_id=user.id, lesson_id=lesson.id,
                status="completed", completed_at=in_window,
            ),
            StudentProgress(
                student_id=user.id, lesson_id=lesson.id,
                status="completed", completed_at=out_of_window,
            ),
            StudentProgress(
                student_id=user.id, lesson_id=lesson.id,
                status="in_progress", completed_at=None,
            ),
        ]
    )
    await db_session.commit()

    stats = await compute_snapshot(
        db_session, user.id, now=datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    )
    assert stats.lessons_completed == 1
