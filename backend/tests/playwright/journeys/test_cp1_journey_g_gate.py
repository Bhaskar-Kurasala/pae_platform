"""D18 Phase B CP1 — Journey (g) gate evaluation + role transition.

Pattern 22 pre-flight finding: `evaluate_student_against_gate` is
a tool, not an HTTP endpoint. It's called from agents via
`get_active_session` contextvar, which means a true end-to-end
gate-pass test would route through career_coach or
project_evaluator — which are LLM-cost paths.

CP1 scope (architect's note: "The role transition itself is mostly
backend; one UI test confirming the post-transition dashboard
renders correctly is sufficient for CP1; CP2 will add edge cases"):
verify the journey fixture's seed shape is correct for the gate to
be evaluable. Stronger gate-pass + transition-write assertions are
deferred to CP2 + CP3 traceability.

Backend-driven; uses Phase A CP4's
`seed_full_journey_through_data_analyst` composite fixture.

Cost class: low (no LLM agents invoked; all DB-shape assertions).
"""

from __future__ import annotations

import os
import uuid as _uuid

import pytest
from playwright.sync_api import Page
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.journey_fixtures import (
    seed_full_journey_through_data_analyst,
)
from tests.playwright.helpers.sync_async_bridge import (
    cleanup_student_via_db,
    mutate_student_state_via_db,
    seed_student_via_db,
)

pytestmark = [pytest.mark.critical_path, pytest.mark.cost("low")]


def test_journey_through_data_analyst_seeds_passing_capstone(
    page: Page,
) -> None:
    """seed_full_journey_through_data_analyst lands a graded capstone.

    Per the CP4 fixture contract, the seeded student has 1 passing
    capstone submission with score=85 against the data-analyst
    course. CP1 (g) verifies that contract holds end-to-end so
    gate-eval logic has the right state to evaluate against.
    """
    journey = seed_student_via_db(seed_full_journey_through_data_analyst)
    student_id = journey.student.user_id
    try:
        async def _check(session: AsyncSession) -> tuple[int | None, str | None]:
            r = await session.execute(
                sql_text(
                    "SELECT score, status FROM exercise_submissions "
                    "WHERE student_id = :sid AND score IS NOT NULL "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"sid": student_id},
            )
            row = r.one_or_none()
            if not row:
                return None, None
            return row.score, row.status

        score, status = mutate_student_state_via_db(_check)
        assert score is not None, (
            "journey fixture should seed at least one graded capstone "
            "submission"
        )
        assert score >= 70, f"expected passing score (>=70), got {score}"
        assert status == "graded"
    finally:
        cleanup_student_via_db(student_id)


def test_journey_through_data_analyst_seeds_two_passing_mock_sessions(
    page: Page,
) -> None:
    """Fixture contract: 2 passing mock_interview agent_actions in last 72h.

    The mock-pass aggregator filters on
    output_data.session_verdict.passed=true; verify 2 such rows
    exist (the gate's mock_interview_status requires N passes).
    """
    journey = seed_student_via_db(seed_full_journey_through_data_analyst)
    student_id = journey.student.user_id
    try:
        async def _count(session: AsyncSession) -> int:
            r = await session.execute(
                sql_text(
                    """
                    SELECT COUNT(*) FROM agent_actions
                    WHERE student_id = :sid
                      AND agent_name = 'mock_interview'
                      AND output_data->'session_verdict'->>'passed' = 'true'
                    """
                ),
                {"sid": student_id},
            )
            return int(r.scalar_one())

        n = mutate_student_state_via_db(_count)
        assert n == 2, (
            f"expected 2 passing mock sessions per fixture contract, "
            f"got {n}"
        )
    finally:
        cleanup_student_via_db(student_id)


def test_journey_through_data_analyst_grants_target_entitlement(
    page: Page,
) -> None:
    """Fixture contract: data-analyst course_entitlements row granted.

    Pattern 22: assert against the actual schema
    (course_entitlements joins via course_id, NOT course_slug —
    surfaced at CP4 retrofit).
    """
    journey = seed_student_via_db(seed_full_journey_through_data_analyst)
    student_id = journey.student.user_id
    try:
        async def _count(session: AsyncSession) -> int:
            r = await session.execute(
                sql_text(
                    """
                    SELECT COUNT(*) FROM course_entitlements ce
                    JOIN courses c ON c.id = ce.course_id
                    WHERE ce.user_id = :uid
                      AND c.slug = 'data-analyst'
                    """
                ),
                {"uid": student_id},
            )
            return int(r.scalar_one())

        assert mutate_student_state_via_db(_count) == 1
    finally:
        cleanup_student_via_db(student_id)
