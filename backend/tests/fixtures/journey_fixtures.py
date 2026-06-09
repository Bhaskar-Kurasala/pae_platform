"""D18 Phase A CP4 — composite journey seeders.

One-call setup for the most common Phase B test scenarios. Each
helper composes primitives from `role_state_fixtures` so a journey
test author can write:

    student = await seed_paid_silent_at_risk_student(db_session)
    await db_session.commit()
    # ... drive page objects against this student ...

instead of stitching together 5–8 individual seed calls per test.

Convention parity with role_state_fixtures:
  * No commit; caller owns the transaction boundary.
  * Returns the underlying SeededStudent so tests can assert on
    user_id, email, role, etc. Composite-specific extras (capstone
    submission ids, mock-session ids) are exposed via attributes on
    the returned dataclass when relevant.
  * Each composite documents the exact retention/gate state it
    leaves the DB in so tests don't have to read the implementation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from .role_state_fixtures import (
    SeededCapstoneSubmission,
    SeededPayment,
    SeededStudent,
    _grant_entitlement,  # type: ignore[attr-defined]
    _seed_risk_signal,  # type: ignore[attr-defined]
    seed_capstone_submission,
    seed_data_analyst_with_entitlement,
    seed_just_passed_mock_data_scientist,
    seed_passing_mock_session,
    seed_payment_intent,
    seed_python_developer_fresh,
    seed_stalled_data_analyst,
)


@dataclass
class SeededJourney:
    """Wraps a SeededStudent with optional composite extras.

    Composite fixtures may attach a payment / submissions / mock-
    session-ids list so tests can assert on the entire seeded surface
    without re-querying.
    """

    student: SeededStudent
    payment: SeededPayment | None = None
    capstone_submissions: list[SeededCapstoneSubmission] = field(default_factory=list)
    passing_mock_action_ids: list[uuid.UUID] = field(default_factory=list)
    notes: str | None = None


# ── 1. Full journey through data_analyst gate ───────────────────────


async def seed_full_journey_through_data_analyst(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
) -> SeededJourney:
    """Student fully ready to clear python_developer→data_analyst gate.

    State after seed:
      * current role: python_developer (entitlement to python-developer)
      * data-analyst entitlement granted (so they can attempt the move)
      * 1 passing capstone submission against data-analyst (score=85)
      * 2 passing mock_interview agent_actions in last 72h targeting
        data_analyst (mock-pass aggregator returns ≥2 / last-3 = pass)
      * No risk signal (None — passing students don't carry slip)
    """
    student = await seed_python_developer_fresh(
        session, email_suffix=email_suffix
    )
    # Grant data-analyst entitlement on top of python-developer base.
    # Reuses the canonical _grant_entitlement helper (resolves
    # course_slug → course_id, fills source/tier defaults). Earlier
    # CP4 attempt to inline raw SQL hit a column-name mismatch
    # (course_entitlements has course_id not course_slug); catching
    # it surfaced the importance of reusing the canonical helper.
    await _grant_entitlement(
        session, student_id=student.user_id, course_slug="data-analyst"
    )
    student.entitled_course_slugs.append("data-analyst")

    submission = await seed_capstone_submission(
        session,
        student_id=student.user_id,
        course_slug="data-analyst",
        score=85,
        status="graded",
    )
    mock_a = await seed_passing_mock_session(
        session, student_id=student.user_id, target_role_slug="data_analyst",
        hours_ago=18,
    )
    mock_b = await seed_passing_mock_session(
        session, student_id=student.user_id, target_role_slug="data_analyst",
        hours_ago=42,
    )
    return SeededJourney(
        student=student,
        capstone_submissions=[submission],
        passing_mock_action_ids=[mock_a, mock_b],
        notes="ready-to-promote: capstone passed + 2 passing mocks",
    )


# ── 2. Paid-silent at-risk student ──────────────────────────────────


async def seed_paid_silent_at_risk_student(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
) -> SeededJourney:
    """Paid 8 days ago, no activity in last 12 days.

    State after seed:
      * student at python_developer with python-developer entitlement
      * 1 succeeded payment dated 8 days ago
      * student_risk_signals: slip_type='paid_silent',
        days_since_last_session=12, paid=TRUE, risk_score=72
      * No learning_sessions / no agent_actions — by construction
        silent.
    """
    student = await seed_python_developer_fresh(
        session, email_suffix=email_suffix
    )
    payment = await seed_payment_intent(
        session, student_id=student.user_id, amount_cents=9900,
        status="succeeded",
    )
    # Backdate the payment ts to 8 days ago for realism.
    eight_days_ago = datetime.now(UTC) - timedelta(days=8)
    await session.execute(
        sql_text(
            "UPDATE payments SET created_at = :ts, updated_at = :ts "
            "WHERE id = :pid"
        ),
        {"ts": eight_days_ago, "pid": payment.payment_id},
    )
    await _seed_risk_signal(
        session,
        student_id=student.user_id,
        slip_type="paid_silent",
        days_since_last_session=12,
        risk_score=72,
    )
    # Mark the risk-signal row paid=TRUE (default is FALSE; paid
    # students get distinct admin treatment).
    await session.execute(
        sql_text(
            "UPDATE student_risk_signals SET paid = TRUE "
            "WHERE user_id = :uid"
        ),
        {"uid": student.user_id},
    )
    return SeededJourney(
        student=student,
        payment=payment,
        notes="paid_silent: paid 8d ago, 12d silent",
    )


# ── 3. Capstone-stalled student ─────────────────────────────────────


async def seed_capstone_stalled_student(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
) -> SeededJourney:
    """Entitled to data-analyst, attempted capstone, stuck 14+ days.

    Reuses the existing seed_stalled_data_analyst (D17b helper) so we
    don't duplicate the canonical capstone-stall shape, then layers on
    a draft capstone submission (score=NULL, status='in_progress')
    and ages the most recent activity to 15 days ago.

    State after seed:
      * student at data_analyst with data-analyst entitlement
      * 1 ungraded capstone submission (score=NULL)
      * student_risk_signals: slip_type='capstone_stalled',
        days_since_last_session=15
    """
    student = await seed_stalled_data_analyst(
        session, email_suffix=email_suffix
    )
    submission = await seed_capstone_submission(
        session,
        student_id=student.user_id,
        course_slug="data-analyst",
        score=None,
        status="in_progress",
    )
    return SeededJourney(
        student=student,
        capstone_submissions=[submission],
        notes="capstone_stalled: ungraded draft + 15d silent",
    )


# ── 4. Streak-broken student ────────────────────────────────────────


async def seed_streak_broken_student(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
) -> SeededJourney:
    """Had 7+ day streak, broke 3 days ago.

    State after seed:
      * student at data_analyst with data-analyst entitlement
      * student_risk_signals: slip_type='streak_broken',
        max_streak_ever=8, days_since_last_session=3
      * No fresh learning_sessions — the streak is broken precisely
        because they stopped 3 days ago.
    """
    student = await seed_data_analyst_with_entitlement(
        session, email_suffix=email_suffix
    )
    await _seed_risk_signal(
        session,
        student_id=student.user_id,
        slip_type="streak_broken",
        days_since_last_session=3,
        risk_score=58,
    )
    await session.execute(
        sql_text(
            "UPDATE student_risk_signals SET max_streak_ever = 8 "
            "WHERE user_id = :uid"
        ),
        {"uid": student.user_id},
    )
    return SeededJourney(
        student=student,
        notes="streak_broken: max=8, broke 3d ago",
    )


# ── 5. Promotion-avoidant student ───────────────────────────────────


async def seed_promotion_avoidant_student(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
) -> SeededJourney:
    """High readiness for next role, no application activity.

    Reuses seed_just_passed_mock_data_scientist (data_scientist with
    a fresh passing mock targeting ml_engineer) — that's the
    ready-to-promote shape — but layers on the promotion_avoidant
    slip signal so admin filters surface them.

    State after seed:
      * student at data_scientist (per the underlying helper)
      * 1 passing mock_interview action targeting ml_engineer
      * student_risk_signals: slip_type='promotion_avoidant',
        days_since_last_session=2, risk_score=45 (not severe;
        the readiness-without-action shape is moderate-tier)
    """
    student = await seed_just_passed_mock_data_scientist(
        session, email_suffix=email_suffix
    )
    await _seed_risk_signal(
        session,
        student_id=student.user_id,
        slip_type="promotion_avoidant",
        days_since_last_session=2,
        risk_score=45,
    )
    return SeededJourney(
        student=student,
        notes="promotion_avoidant: ready, no application",
    )


# ── 6. Cold-signup student ──────────────────────────────────────────


async def seed_cold_signup_student(
    session: AsyncSession,
    *,
    email_suffix: str | None = None,
    days_since_signup: int = 6,
) -> SeededJourney:
    """Signed up >5 days ago, never logged in.

    State after seed:
      * student at python_developer with python-developer entitlement
      * users.created_at backdated to days_since_signup
      * No learning_sessions, no agent_actions
      * student_risk_signals: slip_type='cold_signup',
        days_since_last_session=NULL (never logged in)
    """
    student = await seed_python_developer_fresh(
        session, email_suffix=email_suffix
    )
    when = datetime.now(UTC) - timedelta(days=days_since_signup)
    await session.execute(
        sql_text(
            "UPDATE users SET created_at = :ts, updated_at = :ts "
            "WHERE id = :uid"
        ),
        {"ts": when, "uid": student.user_id},
    )
    await _seed_risk_signal(
        session,
        student_id=student.user_id,
        slip_type="cold_signup",
        days_since_last_session=None,
        risk_score=68,
    )
    return SeededJourney(
        student=student,
        notes=f"cold_signup: registered {days_since_signup}d ago, never logged in",
    )


__all__ = [
    "SeededJourney",
    "seed_capstone_stalled_student",
    "seed_cold_signup_student",
    "seed_full_journey_through_data_analyst",
    "seed_paid_silent_at_risk_student",
    "seed_promotion_avoidant_student",
    "seed_streak_broken_student",
]
