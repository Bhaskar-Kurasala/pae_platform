"""D18 Phase B CP1 — Journey (d) mock interview multi-turn.

Highest-risk CP1 journey per architect notes: first
uses_self_eval=True journey under Playwright. Tests:
  * /mock/sessions/start creates an interview_sessions row +
    returns first_question.
  * /mock/sessions/{id}/answer accepts the answer + returns
    rubric evaluation (or stays well-shaped if rubric defers).
  * session_id roundtrip works (subsequent /answer calls
    reference the same row).

Cost class: high (multi-turn LLM calls; ~₹3-5).
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from playwright.sync_api import Page
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.playwright.helpers.sync_async_bridge import (
    cleanup_student_via_db,
    fetch_token_via_http,
    mutate_student_state_via_db,
    register_via_http,
)

from ._journey_helpers import post_json

pytestmark = [pytest.mark.critical_path, pytest.mark.cost("high")]


@pytest.mark.real_llm
@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG-CP1D-INTERVIEW-SESSIONS-UPDATED-AT: Mock interview "
        "start path raises NotNullViolationError on "
        "interview_sessions.updated_at. Live playwright_test schema "
        "has updated_at NOT NULL with server_default=now(); ORM "
        "model at backend/app/models/interview_session.py:55 has "
        "nullable=True without server_default, so SQLAlchemy "
        "INSERTs explicit NULL (overrides the DB default). "
        "Service writes a row without setting updated_at; INSERT "
        "fails with 500. Note: dev `platform` DB has updated_at "
        "nullable (older migration state), masking the bug there. "
        "Surfaced at CP1D authoring 2026-05-09. LAUNCH-BLOCKER if "
        "production DB matches playwright_test schema. Convention "
        "A: xfail strict=True; remove when fix lands. Fix scope: "
        "either add server_default=sa.func.now() to the ORM "
        "model's updated_at column, or change service to set "
        "updated_at=datetime.now(UTC) on INSERT."
    ),
)
def test_mock_interview_session_starts_and_accepts_one_answer(
    page: Page,
) -> None:
    """Multi-turn shape: start session → first_question → submit answer.

    Reduced from the architect's "full session through summary" to
    "start + 1 turn" for CP1 cost discipline (~₹3-5 budget). CP2
    will exercise the full session-end-to-summary path.

    Verifies:
      * session_id roundtrip works (start returns id, /answer
        accepts it)
      * interview_sessions row landed with status='active'
      * One answer triggered an evaluation (rubric or stub)
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp1d-{suffix}@example.com"
    password = "JourneyD123!"
    user_id = register_via_http(
        email=email, password=password, full_name="CP1D Mock Student",
    )
    token = fetch_token_via_http(email=email, password=password)

    # Mock interview gates on entitlement per the role-aware check.
    async def _grant(session: AsyncSession) -> None:
        from tests.fixtures.role_state_fixtures import _grant_entitlement as _ge

        await _ge(session, student_id=user_id, course_slug="python-developer")

    mutate_student_state_via_db(_grant)

    try:
        # Start a behavioral session — least costly mode.
        start_status, start_body = post_json(
            "/mock/sessions/start",
            token=token,
            body={
                "mode": "behavioral",
                "target_role": "python-developer",
                "level": "junior",
            },
            timeout=120,
        )
        assert start_status == 201, (
            f"start failed: status={start_status} body={start_body}"
        )
        assert start_body is not None
        session_id = start_body["session_id"]
        first_q = start_body.get("first_question") or {}
        assert first_q.get("text"), (
            f"no first_question.text in start response: {start_body!r}"
        )
        question_id = first_q["id"]

        # interview_sessions row landed with active status.
        async def _check_session(session: AsyncSession) -> str:
            r = await session.execute(
                sql_text(
                    "SELECT status FROM interview_sessions "
                    "WHERE id = :sid AND user_id = :uid"
                ),
                {"sid": session_id, "uid": user_id},
            )
            return r.scalar_one()

        assert mutate_student_state_via_db(_check_session) == "active"

        # Submit one answer.
        ans_status, ans_body = post_json(
            f"/mock/sessions/{session_id}/answer",
            token=token,
            body={
                "question_id": question_id,
                "text": (
                    "I'd start by understanding requirements with the "
                    "team, then sketch a small prototype to validate "
                    "assumptions before scaling up. Iterating fast on "
                    "feedback matters more than getting it perfect "
                    "the first time."
                ),
            },
            timeout=120,
        )
        assert ans_status == 200, (
            f"answer failed: status={ans_status} body={ans_body}"
        )
        assert ans_body is not None
        assert ans_body.get("answer_id"), (
            f"no answer_id in response: {ans_body!r}"
        )
        # Evaluation block must exist (shape-check; specific scoring
        # may vary). Pattern 22: don't pin score values.
        evaluation = ans_body.get("evaluation")
        assert evaluation, f"no evaluation in answer response: {ans_body!r}"
    finally:
        cleanup_student_via_db(user_id)
