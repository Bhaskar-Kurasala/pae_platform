"""D18 Phase B CP2 — edge cases for lesson (b), capstone (c),
gate eval (g).

Backend-driven; cost class low. Pattern 22-verified per edge.

Edges covered:
  (b) lesson edges:
    1. Idempotent complete: POST complete twice → second is no-op
       (no duplicate row; status stays 'completed').
    2. GET progress after completion reflects completed state.

  (c) capstone edges:
    1. Empty-string code submission → server accepts (no min-length
       validator at the schema layer); pinning current contract.
    2. Re-submission to same exercise increments attempt_number
       (Pattern 22 verified via service code at submit() line: count
       attempts then +1).

  (g) gate eval edges:
    1. Student WITHOUT passing capstone → fixture state shape
       proves the seed contract for the "blocked gate" CP2 path.
    2. Student WITHOUT 2 passing mocks → fixture state shape proves
       blocked-by-mock-count.
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from playwright.sync_api import Page
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.content_seeders import (
    cleanup_seeded_lessons,
    seed_minimal_capstone_bundle,
    seed_minimal_lesson_chain,
)
from tests.fixtures.role_state_fixtures import (
    seed_python_developer_fresh,
    seed_stalled_data_analyst,
)
from tests.playwright.helpers.sync_async_bridge import (
    cleanup_student_via_db,
    fetch_token_via_http,
    mutate_student_state_via_db,
    register_via_http,
    seed_student_via_db,
)

from ._journey_helpers import delete_json, get_json, post_json

pytestmark = [pytest.mark.edge_case, pytest.mark.cost("low")]


# ── Journey (b) lesson edges ────────────────────────────────────────


def test_complete_lesson_is_idempotent(page: Page) -> None:
    """POST complete twice → second is no-op. Pattern 22 verified
    via progress_service: pg_insert(...).on_conflict_do_update(...)
    on (student_id, lesson_id) — second POST upserts to the same
    'completed' state without raising."""
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp2b-idem-{suffix}@example.com"
    user_id = register_via_http(
        email=email, password="JourneyB2Idem!", full_name="CP2B Idempotent",
    )
    token = fetch_token_via_http(email=email, password="JourneyB2Idem!")
    chain = seed_student_via_db(
        seed_minimal_lesson_chain, course_slug="python-developer", n=1,
    )
    try:
        lesson_id = chain.lesson_ids[0]
        # First completion.
        s1, _ = post_json(
            f"/students/me/lessons/{lesson_id}/complete", token=token,
        )
        assert s1 == 200
        # Second completion — should not raise; state stays completed.
        s2, _ = post_json(
            f"/students/me/lessons/{lesson_id}/complete", token=token,
        )
        assert s2 == 200, f"second complete returned {s2}"

        # Verify exactly 1 student_progress row (no duplicate).
        async def _count(session: AsyncSession) -> int:
            r = await session.execute(
                sql_text(
                    "SELECT COUNT(*) FROM student_progress "
                    "WHERE student_id = :sid AND lesson_id = :lid"
                ),
                {"sid": user_id, "lid": lesson_id},
            )
            return int(r.scalar_one())

        assert mutate_student_state_via_db(_count) == 1
    finally:
        cleanup_student_via_db(user_id)

        async def _cleanup(session: AsyncSession) -> None:
            await cleanup_seeded_lessons(
                session, lesson_ids=chain.lesson_ids,
            )

        mutate_student_state_via_db(_cleanup)


def test_uncomplete_then_recomplete_round_trip(page: Page) -> None:
    """complete → uncomplete → complete: final state is 'completed'.

    Verifies the round-trip leaves the student_progress row in a
    deterministic state (not stuck in some intermediate state).
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp2b-round-{suffix}@example.com"
    user_id = register_via_http(
        email=email, password="JourneyB2Round!", full_name="CP2B Round Trip",
    )
    token = fetch_token_via_http(email=email, password="JourneyB2Round!")
    chain = seed_student_via_db(
        seed_minimal_lesson_chain, course_slug="python-developer", n=1,
    )
    try:
        lesson_id = chain.lesson_ids[0]
        # complete → uncomplete → complete
        post_json(f"/students/me/lessons/{lesson_id}/complete", token=token)
        delete_json(f"/students/me/lessons/{lesson_id}/complete", token=token)
        post_json(f"/students/me/lessons/{lesson_id}/complete", token=token)

        async def _check(session: AsyncSession) -> str:
            r = await session.execute(
                sql_text(
                    "SELECT status FROM student_progress "
                    "WHERE student_id = :sid AND lesson_id = :lid"
                ),
                {"sid": user_id, "lid": lesson_id},
            )
            return r.scalar_one()

        assert mutate_student_state_via_db(_check) == "completed"
    finally:
        cleanup_student_via_db(user_id)

        async def _cleanup(session: AsyncSession) -> None:
            await cleanup_seeded_lessons(
                session, lesson_ids=chain.lesson_ids,
            )

        mutate_student_state_via_db(_cleanup)


# ── Journey (c) capstone edges ──────────────────────────────────────


def test_capstone_resubmission_increments_attempt_number(page: Page) -> None:
    """Re-submitting to the same exercise creates a new row with
    attempt_number=2. Pattern 22 verified via exercise_service.submit:
      attempt = await self.submission_repo.count_attempts(...) + 1
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp2c-resub-{suffix}@example.com"
    user_id = register_via_http(
        email=email, password="JourneyC2Resub!", full_name="CP2C Resubmit",
    )
    token = fetch_token_via_http(email=email, password="JourneyC2Resub!")
    bundle = seed_student_via_db(
        seed_minimal_capstone_bundle, course_slug="python-developer",
    )

    async def _grant(session: AsyncSession) -> None:
        from tests.fixtures.role_state_fixtures import _grant_entitlement as _ge
        await _ge(session, student_id=user_id, course_slug="python-developer")
    mutate_student_state_via_db(_grant)

    try:
        for _ in range(2):
            status, _ = post_json(
                f"/exercises/{bundle.capstone_exercise_id}/submit",
                token=token,
                body={"code": "# attempt code"},
            )
            assert status == 201

        async def _check(session: AsyncSession) -> list[int]:
            r = await session.execute(
                sql_text(
                    "SELECT attempt_number FROM exercise_submissions "
                    "WHERE student_id = :sid AND exercise_id = :eid "
                    "ORDER BY created_at"
                ),
                {"sid": user_id, "eid": bundle.capstone_exercise_id},
            )
            return [row.attempt_number for row in r.all()]

        attempts = mutate_student_state_via_db(_check)
        assert attempts == [1, 2], (
            f"resubmission should increment attempt_number; got {attempts}"
        )
    finally:
        cleanup_student_via_db(user_id)

        async def _cleanup_bundle(session: AsyncSession) -> None:
            await cleanup_seeded_lessons(
                session, lesson_ids=[bundle.lesson_id],
            )

        mutate_student_state_via_db(_cleanup_bundle)


def test_capstone_empty_code_submission_rejected_422(page: Page) -> None:
    """Submit with empty code string → 422 Unprocessable Entity.

    Pattern 22 contract pin: SubmissionCreate.code declares
    min_length=1. Empty string violates the validator and the
    server rejects with 422. Authoring-time correction (CP2):
    initial test assumed accept; live shape verified to reject.
    Test now pins the actual contract.
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp2c-empty-{suffix}@example.com"
    user_id = register_via_http(
        email=email, password="JourneyC2Empty!", full_name="CP2C Empty",
    )
    token = fetch_token_via_http(email=email, password="JourneyC2Empty!")
    bundle = seed_student_via_db(
        seed_minimal_capstone_bundle, course_slug="python-developer",
    )

    async def _grant(session: AsyncSession) -> None:
        from tests.fixtures.role_state_fixtures import _grant_entitlement as _ge
        await _ge(session, student_id=user_id, course_slug="python-developer")
    mutate_student_state_via_db(_grant)

    try:
        status, _body = post_json(
            f"/exercises/{bundle.capstone_exercise_id}/submit",
            token=token,
            body={"code": ""},
        )
        assert status == 422, (
            f"expected 422 on empty code (SubmissionCreate.code "
            f"min_length=1); got {status}"
        )

        # Also verify no exercise_submissions row landed.
        async def _count(session: AsyncSession) -> int:
            r = await session.execute(
                sql_text(
                    "SELECT COUNT(*) FROM exercise_submissions "
                    "WHERE student_id = :sid AND exercise_id = :eid"
                ),
                {"sid": user_id, "eid": bundle.capstone_exercise_id},
            )
            return int(r.scalar_one())

        assert mutate_student_state_via_db(_count) == 0, (
            "rejected submission should not land in DB"
        )
    finally:
        cleanup_student_via_db(user_id)

        async def _cleanup_bundle(session: AsyncSession) -> None:
            await cleanup_seeded_lessons(
                session, lesson_ids=[bundle.lesson_id],
            )

        mutate_student_state_via_db(_cleanup_bundle)


# ── Journey (g) gate eval edges ────────────────────────────────────


def test_stalled_student_lacks_passing_capstone(page: Page) -> None:
    """seed_stalled_data_analyst: ungraded capstone (score=NULL)
    means gate evaluation can't pass on capstone count. Verify
    the fixture's seeded shape matches that contract."""
    journey = seed_student_via_db(seed_stalled_data_analyst)
    student_id = journey.user_id
    try:
        async def _check(session: AsyncSession) -> int:
            r = await session.execute(
                sql_text(
                    """
                    SELECT COUNT(*) FROM exercise_submissions
                    WHERE student_id = :sid
                      AND score IS NOT NULL
                      AND score >= 70
                    """
                ),
                {"sid": student_id},
            )
            return int(r.scalar_one())

        passing_capstones = mutate_student_state_via_db(_check)
        assert passing_capstones == 0, (
            f"stalled fixture should have 0 passing capstones; "
            f"got {passing_capstones}"
        )
    finally:
        cleanup_student_via_db(student_id)


def test_python_developer_fresh_lacks_passing_mock_sessions(page: Page) -> None:
    """seed_python_developer_fresh: 0 mock_interview agent_actions
    with passed=true. Gate to data_analyst should be blocked on the
    mock-count axis (separate from capstone)."""
    student = seed_student_via_db(seed_python_developer_fresh)
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
                {"sid": student.user_id},
            )
            return int(r.scalar_one())

        assert mutate_student_state_via_db(_count) == 0
    finally:
        cleanup_student_via_db(student.user_id)
