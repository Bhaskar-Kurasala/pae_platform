"""Unit tests for the Readiness Overview aggregator.

Pure helpers (8) + action ranker (5) + 2 integration tests covering
empty + populated users.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles


# ── SQLite shim ─────────────────────────────────────────────────────────
# `notebook_entries.tags` uses postgres ARRAY which SQLite can't render —
# map it to TEXT just for the test session. We never touch those rows here.
@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(_type, _compiler, **_kw) -> str:  # type: ignore[no-untyped-def]
    return "TEXT"


def _visit_array(self, _type, **_kw):  # type: ignore[no-untyped-def]
    return "TEXT"


SQLiteTypeCompiler.visit_ARRAY = _visit_array  # type: ignore[attr-defined]

from app.models.exercise import Exercise
from app.models.exercise_submission import ExerciseSubmission
from app.models.goal_contract import GoalContract
from app.models.interview_session import InterviewSession
from app.models.jd_library import JdLibrary
from app.models.lesson import Lesson
from app.models.course import Course
from app.models.mock_interview import MockSessionReport, MockWeaknessLedger
from app.models.portfolio_autopsy_result import PortfolioAutopsyResult
from app.models.readiness import (
    DIAGNOSTIC_STATUS_COMPLETED,
    ReadinessDiagnosticSession,
    ReadinessVerdict,
)
from app.models.readiness_action_completion import ReadinessActionCompletion
from app.models.resume import Resume
from app.models.student_progress import StudentProgress
from app.models.user import User
from app.services.readiness_overview_service import (
    compute_core_skill_score,
    compute_interview_score,
    compute_overall_readiness,
    compute_proof_score,
    compute_targeting_score,
    load_overview,
    rank_actions,
)


# ---------------------------------------------------------------------------
# Pure score helpers (8 tests)
# ---------------------------------------------------------------------------


def test_skill_score_empty_user_is_zero() -> None:
    assert compute_core_skill_score(0, 0) == 0


def test_skill_score_clamps_at_100() -> None:
    assert compute_core_skill_score(50, 50) == 100
    # Hostile inputs (more completed than total) still clamp.
    assert compute_core_skill_score(80, 50) == 100


def test_skill_score_midpoint() -> None:
    assert compute_core_skill_score(5, 10) == 50


def test_proof_score_empty() -> None:
    assert compute_proof_score(0, 0, 0) == 0


def test_proof_score_caps_at_100() -> None:
    # 4 drafts * 30 = 120 → capped to 100.
    assert compute_proof_score(4, 0, 0) == 100


def test_interview_score_empty_list_is_zero() -> None:
    assert compute_interview_score([]) == 0


def test_interview_score_uses_last_three_only() -> None:
    # First 'not_ready' (35) is dropped; last three average to (70+100+70)/3 = 80.
    score = compute_interview_score(
        ["not_ready", "promising", "ready", "promising"]
    )
    assert score == 80


def test_targeting_score_full_components() -> None:
    # 2 JDs * 15 = 30, fit>=70 adds 40, target_role adds 30 → 100.
    assert compute_targeting_score(2, 80.0, True) == 100


def test_overall_weighted_rounding() -> None:
    # 80*0.4 + 60*0.25 + 70*0.2 + 50*0.15 = 32 + 15 + 14 + 7.5 = 68.5 → 68 (banker's) or 69
    overall = compute_overall_readiness(80, 60, 70, 50)
    assert overall in (68, 69)


# ---------------------------------------------------------------------------
# Action ranker (5 tests)
# ---------------------------------------------------------------------------


def _ranker_defaults() -> dict:
    return dict(
        has_open_weakness=False,
        mock_weakness_concept=None,
        jds_saved_count=5,
        days_since_resume_update=2,
        last_fit_score=85.0,
        last_jd_title="Senior Backend",
        days_since_autopsy=3,
        latest_verdict_intent=None,
        latest_verdict_label=None,
        latest_verdict_route=None,
        completed_action_kinds=set(),
    )


def test_rank_actions_open_weakness_takes_priority() -> None:
    actions = rank_actions(
        **{
            **_ranker_defaults(),
            "has_open_weakness": True,
            "mock_weakness_concept": "system_design.scaling",
        }
    )
    assert actions[0].kind == "practice_weakness"
    assert actions[0].route == "interview"
    assert "system_design.scaling" in actions[0].label


def test_rank_actions_no_jds_inserts_add_jd() -> None:
    actions = rank_actions(
        **{
            **_ranker_defaults(),
            "jds_saved_count": 0,
            "days_since_resume_update": 1,
            "last_fit_score": None,
            "last_jd_title": None,
        }
    )
    kinds = [a.kind for a in actions]
    assert "add_jd" in kinds


def test_rank_actions_caps_at_three() -> None:
    # Force every rule to fire.
    actions = rank_actions(
        **{
            **_ranker_defaults(),
            "has_open_weakness": True,
            "mock_weakness_concept": "hashing",
            "jds_saved_count": 0,
            "days_since_resume_update": 90,
            "last_fit_score": 30.0,
            "last_jd_title": "ML Engineer",
            "days_since_autopsy": 60,
            "latest_verdict_intent": "skills_gap",
            "latest_verdict_label": "Spend 20m on retrieval",
            "latest_verdict_route": "/skills/retrieval",
        }
    )
    assert len(actions) == 3


def test_rank_actions_skips_completed_kinds() -> None:
    actions = rank_actions(
        **{
            **_ranker_defaults(),
            "jds_saved_count": 0,
            "completed_action_kinds": {"add_jd"},
            "days_since_resume_update": 1,
            "last_fit_score": None,
            "last_jd_title": None,
        }
    )
    kinds = [a.kind for a in actions]
    assert "add_jd" not in kinds


def test_rank_actions_close_gap_when_fit_low() -> None:
    actions = rank_actions(
        **{
            **_ranker_defaults(),
            "has_open_weakness": False,
            "jds_saved_count": 3,
            "days_since_resume_update": 1,
            "last_fit_score": 45.0,
            "last_jd_title": "DevRel Lead",
            "days_since_autopsy": 1,
        }
    )
    kinds = [a.kind for a in actions]
    assert "close_gap_on_jd" in kinds
    close = next(a for a in actions if a.kind == "close_gap_on_jd")
    assert "DevRel Lead" in close.label


# ---------------------------------------------------------------------------
# Integration: load_overview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_overview_empty_user(db_session: AsyncSession) -> None:
    user = User(
        email="empty@over.dev",
        full_name="Empty Tester",
        hashed_password="x",
        role="student",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    result = await load_overview(db_session, user=user)

    assert result.user_first_name == "Empty"
    assert result.target_role is None
    assert result.overall_readiness == 0
    assert result.sub_scores.skill == 0
    assert result.sub_scores.proof == 0
    assert result.sub_scores.interview == 0
    assert result.sub_scores.targeting == 0
    assert result.latest_verdict is None
    # Empty users still get fallback actions (add_jd + refresh_resume + run_autopsy).
    assert len(result.top_actions) >= 1
    kinds = {a.kind for a in result.top_actions}
    assert "add_jd" in kinds
    # 8 trend points, oldest → newest.
    assert len(result.trend_8w) == 8


@pytest.mark.asyncio
async def test_load_overview_populated_user(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    user = User(
        email="pop@over.dev",
        full_name="Populated Pat",
        hashed_password="x",
        role="student",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Goal contract → target_role
    db_session.add(
        GoalContract(
            user_id=user.id,
            motivation="career",
            deadline_months=6,
            success_statement="Land a senior backend role",
            target_role="Senior Backend Engineer",
        )
    )

    # 2 lessons (1 completed) → skill_score = 50
    course = Course(
        title="C",
        slug="c",
        description="d",
        difficulty="medium",
        price_cents=0,
    )
    db_session.add(course)
    await db_session.flush()
    lesson1 = Lesson(
        course_id=course.id, title="L1", slug="l1", order=1, is_published=True
    )
    lesson2 = Lesson(
        course_id=course.id, title="L2", slug="l2", order=2, is_published=True
    )
    db_session.add_all([lesson1, lesson2])
    await db_session.flush()
    db_session.add(
        StudentProgress(
            student_id=user.id,
            lesson_id=lesson1.id,
            status="completed",
            completed_at=now - timedelta(days=2),
        )
    )

    # Capstone exercise + 1 draft → proof contribution
    capstone = Exercise(
        lesson_id=lesson1.id,
        title="Capstone X",
        exercise_type="coding",
        difficulty="hard",
        is_capstone=True,
    )
    db_session.add(capstone)
    await db_session.flush()
    db_session.add(
        ExerciseSubmission(
            student_id=user.id,
            exercise_id=capstone.id,
            code="print('hi')",
            status="graded",
            score=80,
        )
    )

    # JD library (1 saved, fit 80)
    db_session.add(
        JdLibrary(
            user_id=user.id,
            title="Backend Eng",
            company="Acme",
            jd_text="...",
            last_fit_score=80.0,
        )
    )

    # Resume
    db_session.add(
        Resume(
            user_id=user.id,
            title="My Resume",
            updated_at=now - timedelta(days=3),
        )
    )

    # Autopsy (recent)
    db_session.add(
        PortfolioAutopsyResult(
            user_id=user.id,
            project_title="Side Project",
            project_description="An LLM app",
            headline="Solid scope discipline",
            overall_score=78,
            axes={},
            what_worked=[],
            what_to_do_differently=[],
            production_gaps=[],
        )
    )

    # Mock session + report (verdict=ready)
    sess = InterviewSession(
        user_id=user.id, mode="behavioral", status="completed"
    )
    db_session.add(sess)
    await db_session.flush()
    db_session.add(
        MockSessionReport(
            session_id=sess.id,
            verdict="ready",
            headline="Strong session",
        )
    )

    # Open weakness → drives top action
    db_session.add(
        MockWeaknessLedger(
            user_id=user.id,
            concept="system_design.caching",
            severity=0.9,
            last_seen_at=now,
        )
    )

    await db_session.commit()

    result = await load_overview(db_session, user=user, now=now)

    assert result.user_first_name == "Populated"
    assert result.target_role == "Senior Backend Engineer"
    assert result.sub_scores.skill == 50
    assert result.sub_scores.proof >= 30  # 1 draft → 30
    assert result.sub_scores.interview == 100  # one 'ready' verdict
    assert result.sub_scores.targeting == 85  # 1*15 + 40 + 30
    assert result.overall_readiness > 0

    # Open weakness is the top action.
    assert result.top_actions[0].kind == "practice_weakness"
    assert "system_design.caching" in result.top_actions[0].label
