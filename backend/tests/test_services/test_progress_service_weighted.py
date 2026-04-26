"""Tests for the weighted-progress refactor of ProgressService.

The old `overall_progress` was a mean-of-percentages, which over-weighted
small courses. The Today refactor switches to lessons_completed_total /
lessons_total. New fields also appear: lessons_total,
lessons_completed_total, active_course_id, active_course_title,
next_lesson_id, next_lesson_title, today_unlock_percentage (capped at 25%).

NOTE: We construct StudentProgress directly via the ORM rather than calling
ProgressService.complete_lesson — the latter uses
postgresql.dialects.insert(...).on_conflict_do_update which SQLite cannot
render.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.lesson import Lesson
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.services.progress_service import ProgressService


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, email: str = "p@test.dev") -> User:
    u = User(email=email, full_name="Progress", role="student")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_course(
    db: AsyncSession, *, slug: str, title: str = "Course"
) -> Course:
    c = Course(title=title, slug=slug, description="d", difficulty="beginner")
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def _make_lesson(
    db: AsyncSession,
    course: Course,
    *,
    slug: str,
    order: int = 1,
    title: str | None = None,
) -> Lesson:
    lesson = Lesson(
        course_id=course.id,
        title=title or f"Lesson {order}",
        slug=slug,
        order=order,
        duration_seconds=60,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def _enroll(
    db: AsyncSession, user: User, course: Course
) -> Enrollment:
    e = Enrollment(
        student_id=user.id,
        course_id=course.id,
        status="active",
        enrolled_at=datetime.now(UTC),
        progress_pct=0.0,
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return e


async def _complete(
    db: AsyncSession,
    user: User,
    lesson: Lesson,
    *,
    when: datetime | None = None,
) -> StudentProgress:
    rec = StudentProgress(
        student_id=user.id,
        lesson_id=lesson.id,
        status="completed",
        completed_at=when or datetime.now(UTC),
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return rec


# ---------------------------------------------------------------------------
# overall_progress is WEIGHTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overall_is_weighted_across_lessons_not_mean_of_courses(
    db_session: AsyncSession,
) -> None:
    """A 1-of-1 small course + a 1-of-9 big course = 2/10 = 20%, not 50% + 11% / 2."""
    user = await _make_user(db_session)
    small = await _make_course(db_session, slug="small")
    big = await _make_course(db_session, slug="big")
    await _enroll(db_session, user, small)
    await _enroll(db_session, user, big)

    s_lesson = await _make_lesson(db_session, small, slug="s1")
    big_lessons = [
        await _make_lesson(db_session, big, slug=f"b{i}", order=i)
        for i in range(1, 10)
    ]

    await _complete(db_session, user, s_lesson)
    await _complete(db_session, user, big_lessons[0])

    resp = await ProgressService(db_session).get_student_progress(user)
    assert resp.lessons_total == 10
    assert resp.lessons_completed_total == 2
    assert resp.overall_progress == 20.0  # 2/10 * 100, not 55.6 from mean-of-pcts


@pytest.mark.asyncio
async def test_overall_is_zero_when_no_lessons_exist(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="empty")
    await _enroll(db_session, user, course)
    resp = await ProgressService(db_session).get_student_progress(user)
    assert resp.lessons_total == 0
    assert resp.overall_progress == 0.0
    assert resp.today_unlock_percentage == 0.0


@pytest.mark.asyncio
async def test_no_enrollments_returns_empty_response(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    resp = await ProgressService(db_session).get_student_progress(user)
    assert resp.courses == []
    assert resp.overall_progress == 0.0
    assert resp.lessons_total == 0
    assert resp.lessons_completed_total == 0
    assert resp.active_course_id is None


# ---------------------------------------------------------------------------
# active_course detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_course_is_most_recently_touched(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    a = await _make_course(db_session, slug="a", title="Alpha")
    b = await _make_course(db_session, slug="b", title="Beta")
    await _enroll(db_session, user, a)
    await _enroll(db_session, user, b)

    a_lesson = await _make_lesson(db_session, a, slug="a1")
    b_lesson = await _make_lesson(db_session, b, slug="b1")
    b_lesson_2 = await _make_lesson(
        db_session, b, slug="b2", order=2, title="Beta L2"
    )

    # Older completion in A; more-recent in B → B is active.
    older = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)
    newer = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    await _complete(db_session, user, a_lesson, when=older)
    rec_b = await _complete(db_session, user, b_lesson, when=newer)
    rec_b.updated_at = newer + timedelta(hours=1)
    await db_session.commit()

    resp = await ProgressService(db_session).get_student_progress(user)
    assert resp.active_course_id == b.id
    assert resp.active_course_title == "Beta"
    # Next lesson in active course is the next non-completed (Beta L2).
    assert resp.next_lesson_id == b_lesson_2.id
    assert resp.next_lesson_title == "Beta L2"


@pytest.mark.asyncio
async def test_active_course_falls_back_to_first_enrollment_when_no_progress(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    a = await _make_course(db_session, slug="a-fb")
    await _enroll(db_session, user, a)
    await _make_lesson(db_session, a, slug="a-fb-1")
    resp = await ProgressService(db_session).get_student_progress(user)
    assert resp.active_course_id == a.id


# ---------------------------------------------------------------------------
# today_unlock_percentage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_today_unlock_capped_at_25(db_session: AsyncSession) -> None:
    """Tiny course (2 lessons) would give 50% per lesson — must cap at 25."""
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="tiny")
    await _enroll(db_session, user, course)
    await _make_lesson(db_session, course, slug="t1", order=1)
    await _make_lesson(db_session, course, slug="t2", order=2)
    resp = await ProgressService(db_session).get_student_progress(user)
    assert resp.today_unlock_percentage == 25.0


@pytest.mark.asyncio
async def test_today_unlock_uses_per_lesson_pct_for_large_course(
    db_session: AsyncSession,
) -> None:
    """10 lessons → each is 10%, well below 25 cap."""
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="big-unlock")
    await _enroll(db_session, user, course)
    for i in range(1, 11):
        await _make_lesson(db_session, course, slug=f"bu-{i}", order=i)
    resp = await ProgressService(db_session).get_student_progress(user)
    assert resp.today_unlock_percentage == 10.0


@pytest.mark.asyncio
async def test_today_unlock_zero_when_course_complete(
    db_session: AsyncSession,
) -> None:
    """A finished course offers no unlock."""
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="done")
    await _enroll(db_session, user, course)
    lesson = await _make_lesson(db_session, course, slug="done-1")
    await _complete(db_session, user, lesson)
    resp = await ProgressService(db_session).get_student_progress(user)
    assert resp.today_unlock_percentage == 0.0
    assert resp.next_lesson_id is None


# ---------------------------------------------------------------------------
# Per-exercise pass_score threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exercise_pass_uses_per_exercise_pass_score(
    db_session: AsyncSession,
) -> None:
    """An exercise with pass_score=90 must NOT count as passed at score 80."""
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="ex-pass")
    await _enroll(db_session, user, course)
    lesson = await _make_lesson(db_session, course, slug="ex-l")

    strict = Exercise(
        lesson_id=lesson.id,
        title="Strict",
        difficulty="hard",
        pass_score=90,
    )
    lenient = Exercise(
        lesson_id=lesson.id,
        title="Lenient",
        difficulty="easy",
        pass_score=50,
    )
    db_session.add_all([strict, lenient])
    await db_session.commit()
    await db_session.refresh(strict)
    await db_session.refresh(lenient)

    db_session.add_all(
        [
            ExerciseSubmission(
                student_id=user.id,
                exercise_id=strict.id,
                status="graded",
                score=80,  # below 90 → not passed
            ),
            ExerciseSubmission(
                student_id=user.id,
                exercise_id=lenient.id,
                status="graded",
                score=60,  # above 50 → passed
            ),
        ]
    )
    await db_session.commit()

    resp = await ProgressService(db_session).get_student_progress(user)
    assert resp.total_exercises == 2
    assert resp.exercises_completed == 1  # only the lenient one


@pytest.mark.asyncio
async def test_exercise_pass_default_threshold_is_70(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    course = await _make_course(db_session, slug="ex-default")
    await _enroll(db_session, user, course)
    lesson = await _make_lesson(db_session, course, slug="ex-d-l")
    ex = Exercise(lesson_id=lesson.id, title="E", difficulty="medium")
    db_session.add(ex)
    await db_session.commit()
    await db_session.refresh(ex)

    db_session.add(
        ExerciseSubmission(
            student_id=user.id,
            exercise_id=ex.id,
            status="graded",
            score=70,  # exactly at default threshold → passes
        )
    )
    await db_session.commit()

    resp = await ProgressService(db_session).get_student_progress(user)
    assert resp.exercises_completed == 1
