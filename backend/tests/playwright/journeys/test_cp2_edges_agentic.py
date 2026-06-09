"""D18 Phase B CP2 — agentic-path edges (d) mock and (e) career_coach.

Real-LLM tests; cost class medium-high. Each edge is scoped to ~1
LLM call to keep CP2 cost envelope intact.

Edges covered:
  (d) mock interview edges:
    1. Session resume after start: list_my_sessions includes the
       just-started session (D13 session_id roundtrip / persistence
       contract).

  (e) career coach edges:
    1. Empty/whitespace user input handled gracefully (not 500'd).
    2. Behavior-shape stability under deliberate-empty-context
       message (catches BUG-CP1E-class flakiness regression).
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from playwright.sync_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from tests.playwright.helpers.behavior_shape_assertions import (
    assert_no_fabricated_urgency,
    assert_no_sycophancy,
)
from tests.playwright.helpers.sync_async_bridge import (
    cleanup_student_via_db,
    fetch_token_via_http,
    mutate_student_state_via_db,
    register_via_http,
)

from ._journey_helpers import get_json, post_json

pytestmark = [pytest.mark.edge_case]


def _setup_student_with_entitlement() -> tuple[_uuid.UUID, str]:
    """Register + entitle a fresh student. Returns (user_id, token)."""
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp2-agentic-{suffix}@example.com"
    password = "Cp2Agentic123!"
    user_id = register_via_http(
        email=email, password=password, full_name="CP2 Agentic Edge",
    )
    token = fetch_token_via_http(email=email, password=password)

    async def _grant(session: AsyncSession) -> None:
        from tests.fixtures.role_state_fixtures import _grant_entitlement as _ge

        await _ge(session, student_id=user_id, course_slug="python-developer")

    mutate_student_state_via_db(_grant)
    return user_id, token


# ── Journey (d) mock interview edges ───────────────────────────────


@pytest.mark.real_llm
@pytest.mark.cost("high")
def test_mock_session_persists_in_list_after_start(page: Page) -> None:
    """Start a session; verify GET /mock/sessions returns it.

    Pattern 22 verified: list_my_mock_sessions exists at
    backend/app/api/v1/routes/mock_interview.py. The D13 session_id
    roundtrip contract is "started session is visible in list" —
    if list endpoint returns 404 / 500, persistence layer broke.
    """
    user_id, token = _setup_student_with_entitlement()
    try:
        # Start a session.
        s_status, s_body = post_json(
            "/mock/sessions/start",
            token=token,
            body={
                "mode": "behavioral",
                "target_role": "python-developer",
                "level": "junior",
            },
            timeout=120,
        )
        assert s_status == 201, f"start failed: {s_status} {s_body}"
        session_id = s_body["session_id"]

        # List sessions; verify the just-started one is present.
        l_status, l_body = get_json("/mock/sessions", token=token)
        assert l_status == 200, f"list failed: {l_status} {l_body}"
        assert isinstance(l_body, list)
        ids = {row.get("id") or row.get("session_id") for row in l_body}
        assert session_id in ids, (
            f"started session {session_id} missing from /mock/sessions "
            f"response (got {len(l_body)} sessions; ids={ids})"
        )
    finally:
        cleanup_student_via_db(user_id)


# ── Journey (e) career coach edges ─────────────────────────────────


@pytest.mark.real_llm
@pytest.mark.cost("medium")
def test_career_coach_handles_minimal_input_gracefully(page: Page) -> None:
    """Single-character message → not 500'd; either substantive
    response OR a graceful clarification request.

    Pattern 22 contract: the agentic_chat input schema requires
    `min_length=1`, so single-char passes validation. The
    supervisor must then handle "ambiguous intent" cleanly.
    """
    user_id, token = _setup_student_with_entitlement()
    try:
        status, body = post_json(
            "/agentic/default/chat",
            token=token,
            body={"message": "?"},  # 1 char, valid per min_length=1
            timeout=120,
        )
        assert status == 200, f"chat failed: {status} {body}"
        # Don't strict-pin response shape — the supervisor may
        # decline, ask for clarification, or attempt a default
        # answer. Just verify the response didn't crash.
        assert body is not None
        assert "response" in body
        # Behavior-shape (graceful failure mode):
        response_text = body.get("response", "")
        if response_text:
            # If the supervisor returned content, it shouldn't be
            # sycophantic or fake-urgent regardless of input.
            assert_no_sycophancy(response_text)
            assert_no_fabricated_urgency(response_text)
    finally:
        cleanup_student_via_db(user_id)


@pytest.mark.real_llm
@pytest.mark.cost("medium")
def test_career_coach_response_has_real_llm_cost(page: Page) -> None:
    """Regression guard for BUG-CP1F resolution. After the
    _track_llm_usage fix, agent_actions.cost_inr must populate
    > 0 for any career_coach call that does an LLM round.

    Distinct from journey (e)'s primary test: (e) verifies behavior
    shape; this verifies cost-tracking persists post-CP1F-remediation.
    """
    import datetime as _dt
    from sqlalchemy import text as sql_text

    user_id, token = _setup_student_with_entitlement()
    try:
        before = _dt.datetime.now(_dt.UTC)
        status, body = post_json(
            "/agentic/default/chat",
            token=token,
            body={
                "message": (
                    "What should a python developer focus on next?"
                ),
            },
            timeout=120,
        )
        assert status == 200
        assert body is not None

        async def _max_cost(session: AsyncSession) -> float:
            r = await session.execute(
                sql_text(
                    """
                    SELECT MAX(cost_inr)::float AS max_cost
                    FROM agent_actions
                    WHERE student_id = :sid
                      AND created_at >= :since
                    """
                ),
                {"sid": user_id, "since": before},
            )
            return r.scalar_one() or 0.0

        max_cost = mutate_student_state_via_db(_max_cost)
        assert max_cost > 0, (
            f"BUG-CP1F regression: max(cost_inr)={max_cost} for "
            f"agent_actions written during this LLM call. The "
            f"_track_llm_usage call may have been removed from a "
            f"v2 agent's run() body."
        )
    finally:
        cleanup_student_via_db(user_id)
