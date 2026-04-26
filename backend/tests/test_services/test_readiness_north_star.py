"""North-star instrumentation tests.

Coverage:

  1. record_click stamps the timestamp + idempotency.
  2. record_click rejects sessions without a verdict.
  3. check_completion no-ops when the student hasn't clicked yet.
  4. check_completion is idempotent when completed_at is already set.
  5. Per-intent completion criteria — one test per intent confirming
     the right activity signal triggers stamping:
       - skills_gap   → student_progress.completed_at OR
                        exercise_submission.created_at
       - story_gap    → tailored_resume.created_at OR resume.updated_at
       - interview_gap → interview_session.created_at
       - jd_target_unclear → jd_match_score.created_at
       - ready_but_stalling / ready_to_apply → tailored_resume OR
                        interview_session (apply-flow proxy)
       - thin_data → any of the above (catch-all)
  6. completed_within_window distinguishes <24h from >24h activity
     (the window flag, not the stamping itself — late completions
     still get stamped for funnel visibility).
  7. compute_north_star_rate computes the two rates correctly given
     a small mixed fixture.
  8. compute_north_star_rate window_days bounds.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.interview_session import InterviewSession
from app.models.jd_decoder import JdAnalysis, JdMatchScore
from app.models.lesson import Lesson
from app.models.readiness import (
    DIAGNOSTIC_STATUS_COMPLETED,
    ReadinessDiagnosticSession,
    ReadinessVerdict,
)
from app.models.resume import Resume
from app.models.student_progress import StudentProgress
from app.models.tailored_resume import TailoredResume
from app.models.user import User
from app.services.readiness_north_star import (
    COMPLETION_WINDOW,
    INTENT_CRITERIA,
    SessionMissingVerdictError,
    check_completion,
    compute_north_star_rate,
    record_click,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"{uuid.uuid4()}@test.local",
        full_name="North Star Tester",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


async def _seed_completed_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    intent: str = "skills_gap",
    started_at: datetime | None = None,
    clicked_at: datetime | None = None,
    completed_at_field: datetime | None = None,
) -> tuple[ReadinessDiagnosticSession, ReadinessVerdict]:
    """Seed a finalized session + verdict. Optionally pre-stamp the
    click + completion fields."""
    session = ReadinessDiagnosticSession(
        user_id=user_id,
        status=DIAGNOSTIC_STATUS_COMPLETED,
        started_at=started_at or datetime.now(UTC) - timedelta(hours=1),
        completed_at=datetime.now(UTC),
        next_action_clicked_at=clicked_at,
        next_action_completed_at=completed_at_field,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    verdict = ReadinessVerdict(
        session_id=session.id,
        headline="Test verdict.",
        evidence=[],
        next_action_intent=intent,
        next_action_route="/test",
        next_action_label="Take the action",
    )
    db.add(verdict)
    await db.commit()
    await db.refresh(verdict)

    session.verdict_id = verdict.id
    await db.commit()
    return session, verdict


async def _make_lesson(
    db: AsyncSession, *, slug_suffix: str = ""
) -> uuid.UUID:
    course = Course(
        slug=f"north-star-course-{uuid.uuid4().hex[:6]}{slug_suffix}",
        title="Test course",
        description="x",
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)

    lesson = Lesson(
        course_id=course.id,
        title="Test lesson",
        slug=f"lesson-{uuid.uuid4().hex[:6]}",
        order=1,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson.id


async def _make_exercise(db: AsyncSession) -> uuid.UUID:
    course = Course(
        slug=f"ns-ex-course-{uuid.uuid4().hex[:6]}",
        title="Exercise course",
        description="x",
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    lesson = Lesson(
        course_id=course.id,
        title="Exercise lesson",
        slug=f"ex-lesson-{uuid.uuid4().hex[:6]}",
        order=1,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    ex = Exercise(
        lesson_id=lesson.id,
        title="Test exercise",
        difficulty="easy",
    )
    db.add(ex)
    await db.commit()
    await db.refresh(ex)
    return ex.id


# ---------------------------------------------------------------------------
# Click beacon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_click_stamps_and_is_idempotent(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    session, _v = await _seed_completed_session(db_session, user_id)

    t1 = await record_click(
        db_session, user_id=user_id, session_id=session.id
    )
    t2 = await record_click(
        db_session, user_id=user_id, session_id=session.id
    )
    assert t1 is not None
    # Second call returns the SAME timestamp — no clock drift.
    assert t1 == t2

    refreshed = (
        await db_session.execute(
            select(ReadinessDiagnosticSession).where(
                ReadinessDiagnosticSession.id == session.id
            )
        )
    ).scalar_one()
    assert refreshed.next_action_clicked_at is not None


@pytest.mark.asyncio
async def test_record_click_rejects_session_without_verdict(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    session = ReadinessDiagnosticSession(
        user_id=user_id, status=DIAGNOSTIC_STATUS_COMPLETED
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    with pytest.raises(SessionMissingVerdictError):
        await record_click(
            db_session, user_id=user_id, session_id=session.id
        )


# ---------------------------------------------------------------------------
# check_completion lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_completion_noops_when_not_clicked(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    session, _v = await _seed_completed_session(db_session, user_id)
    result = await check_completion(
        db_session, user_id=user_id, session_id=session.id
    )
    assert result.clicked_at is None
    assert result.completed_at is None
    assert result.completed_within_window is False


@pytest.mark.asyncio
async def test_check_completion_idempotent_when_already_stamped(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    clicked = datetime.now(UTC) - timedelta(hours=2)
    completed = clicked + timedelta(hours=1)
    session, _v = await _seed_completed_session(
        db_session,
        user_id,
        clicked_at=clicked,
        completed_at_field=completed,
    )
    result = await check_completion(
        db_session, user_id=user_id, session_id=session.id
    )
    assert result.completed_at == completed
    assert result.completed_within_window is True


# ---------------------------------------------------------------------------
# Per-intent criteria
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skills_gap_completes_via_lesson(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    clicked = datetime.now(UTC) - timedelta(minutes=30)
    session, _v = await _seed_completed_session(
        db_session, user_id, intent="skills_gap", clicked_at=clicked
    )
    lesson_id = await _make_lesson(db_session)
    db_session.add(
        StudentProgress(
            student_id=user_id,
            lesson_id=lesson_id,
            status="completed",
            completed_at=clicked + timedelta(minutes=10),
        )
    )
    await db_session.commit()

    result = await check_completion(
        db_session, user_id=user_id, session_id=session.id
    )
    assert result.completed_at is not None
    assert result.completed_within_window is True


@pytest.mark.asyncio
async def test_skills_gap_completes_via_exercise(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    clicked = datetime.now(UTC) - timedelta(minutes=30)
    session, _v = await _seed_completed_session(
        db_session, user_id, intent="skills_gap", clicked_at=clicked
    )
    ex_id = await _make_exercise(db_session)
    sub = ExerciseSubmission(
        student_id=user_id,
        exercise_id=ex_id,
        status="passed",
    )
    db_session.add(sub)
    await db_session.commit()

    result = await check_completion(
        db_session, user_id=user_id, session_id=session.id
    )
    assert result.completed_at is not None
    assert result.completed_within_window is True


@pytest.mark.asyncio
async def test_interview_gap_completes_via_mock_session(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    clicked = datetime.now(UTC) - timedelta(minutes=30)
    session, _v = await _seed_completed_session(
        db_session, user_id, intent="interview_gap", clicked_at=clicked
    )
    db_session.add(
        InterviewSession(
            user_id=user_id,
            mode="behavioral",
            target_role="Junior Python Developer",
            level="junior",
        )
    )
    await db_session.commit()

    result = await check_completion(
        db_session, user_id=user_id, session_id=session.id
    )
    assert result.completed_at is not None
    assert result.completed_within_window is True


@pytest.mark.asyncio
async def test_story_gap_completes_via_tailored_resume(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    clicked = datetime.now(UTC) - timedelta(minutes=30)
    session, _v = await _seed_completed_session(
        db_session, user_id, intent="story_gap", clicked_at=clicked
    )
    resume = Resume(user_id=user_id)
    db_session.add(resume)
    await db_session.commit()
    await db_session.refresh(resume)
    db_session.add(
        TailoredResume(
            user_id=user_id,
            base_resume_id=resume.id,
            jd_text="A JD",
            content={"summary": "x"},
        )
    )
    await db_session.commit()

    result = await check_completion(
        db_session, user_id=user_id, session_id=session.id
    )
    assert result.completed_at is not None
    assert result.completed_within_window is True


@pytest.mark.asyncio
async def test_jd_target_unclear_completes_via_match_score(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    clicked = datetime.now(UTC) - timedelta(minutes=30)
    session, _v = await _seed_completed_session(
        db_session, user_id, intent="jd_target_unclear", clicked_at=clicked
    )
    analysis = JdAnalysis(
        jd_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",  # 64 chars
        jd_text_truncated="x" * 60,
        parsed={},
        analysis={},
    )
    db_session.add(analysis)
    await db_session.commit()
    await db_session.refresh(analysis)
    db_session.add(
        JdMatchScore(
            user_id=user_id,
            jd_analysis_id=analysis.id,
            score=70,
            headline="ok",
            evidence=[],
            next_action_intent="skills_gap",
            next_action_route="/x",
            next_action_label="Open",
        )
    )
    await db_session.commit()

    result = await check_completion(
        db_session, user_id=user_id, session_id=session.id
    )
    assert result.completed_at is not None
    assert result.completed_within_window is True


@pytest.mark.asyncio
async def test_ready_but_stalling_completes_via_either_proxy(
    db_session: AsyncSession,
) -> None:
    """Apply-flow signal doesn't exist yet (Phase 2 gap). Either a
    tailored resume OR a mock session should count as completion."""
    user_id = await _make_user(db_session)
    clicked = datetime.now(UTC) - timedelta(minutes=30)
    session, _v = await _seed_completed_session(
        db_session,
        user_id,
        intent="ready_but_stalling",
        clicked_at=clicked,
    )
    db_session.add(
        InterviewSession(
            user_id=user_id,
            mode="behavioral",
            target_role="Senior Engineer",
            level="senior",
        )
    )
    await db_session.commit()

    result = await check_completion(
        db_session, user_id=user_id, session_id=session.id
    )
    assert result.completed_at is not None


@pytest.mark.asyncio
async def test_thin_data_completes_via_any_activity(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    clicked = datetime.now(UTC) - timedelta(minutes=30)
    session, _v = await _seed_completed_session(
        db_session, user_id, intent="thin_data", clicked_at=clicked
    )
    lesson_id = await _make_lesson(db_session)
    db_session.add(
        StudentProgress(
            student_id=user_id,
            lesson_id=lesson_id,
            status="completed",
            completed_at=clicked + timedelta(minutes=15),
        )
    )
    await db_session.commit()

    result = await check_completion(
        db_session, user_id=user_id, session_id=session.id
    )
    assert result.completed_at is not None
    assert result.completed_within_window is True


# ---------------------------------------------------------------------------
# 24h window flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_late_completion_stamped_but_not_within_window(
    db_session: AsyncSession,
) -> None:
    """Late activity (>24h) still gets stamped — completed_at is the
    "when" field; the window flag is what gates the metric."""
    user_id = await _make_user(db_session)
    clicked = datetime.now(UTC) - timedelta(days=2)
    session, _v = await _seed_completed_session(
        db_session, user_id, intent="skills_gap", clicked_at=clicked
    )
    lesson_id = await _make_lesson(db_session)
    db_session.add(
        StudentProgress(
            student_id=user_id,
            lesson_id=lesson_id,
            status="completed",
            completed_at=clicked + timedelta(hours=30),  # >24h after click
        )
    )
    await db_session.commit()

    result = await check_completion(
        db_session, user_id=user_id, session_id=session.id
    )
    assert result.completed_at is not None
    assert result.completed_within_window is False


# ---------------------------------------------------------------------------
# Aggregate rate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_north_star_rate_basic(
    db_session: AsyncSession,
) -> None:
    user_id = await _make_user(db_session)
    now = datetime.now(UTC)

    # 3 finalized sessions, 2 clicked, 1 completed within 24h, 1 outside.
    await _seed_completed_session(
        db_session, user_id, started_at=now - timedelta(hours=2)
    )  # has_verdict but not clicked
    clicked = now - timedelta(hours=10)
    await _seed_completed_session(
        db_session,
        user_id,
        started_at=now - timedelta(hours=11),
        clicked_at=clicked,
        completed_at_field=clicked + timedelta(hours=2),
    )  # clicked + completed within 24h
    clicked2 = now - timedelta(days=2)
    await _seed_completed_session(
        db_session,
        user_id,
        started_at=now - timedelta(days=2, hours=1),
        clicked_at=clicked2,
        completed_at_field=clicked2 + timedelta(hours=30),
    )  # clicked + completed BUT outside the 24h window

    rate = await compute_north_star_rate(
        db_session, window_days=14, now=now
    )
    assert rate.sessions_with_verdict == 3
    assert rate.sessions_clicked == 2
    assert rate.sessions_completed_within_24h == 1
    assert rate.click_through_rate == pytest.approx(2 / 3, abs=1e-3)
    assert rate.completion_within_24h_rate == pytest.approx(1 / 2, abs=1e-3)


@pytest.mark.asyncio
async def test_compute_north_star_rate_empty_period_does_not_divide_by_zero(
    db_session: AsyncSession,
) -> None:
    rate = await compute_north_star_rate(db_session, window_days=14)
    assert rate.sessions_with_verdict == 0
    assert rate.click_through_rate == 0.0
    assert rate.completion_within_24h_rate == 0.0


# ---------------------------------------------------------------------------
# Documentation surface
# ---------------------------------------------------------------------------


def test_intent_criteria_covers_every_routable_intent() -> None:
    """The router knows N intents; the completion criteria table must
    cover all of them so the dashboard never has an unexplained
    "intent X not measured" gap."""
    from app.services.readiness_action_router import known_intents

    for intent in known_intents():
        assert intent in INTENT_CRITERIA, (
            f"intent {intent!r} is routable but has no documented "
            f"completion criterion in INTENT_CRITERIA"
        )


def test_completion_window_is_24_hours() -> None:
    """Pinned constant — the metric definition. If this changes,
    IMPLEMENTATION_NOTES + dashboard need updating in the same PR."""
    assert timedelta(hours=24) == COMPLETION_WINDOW
