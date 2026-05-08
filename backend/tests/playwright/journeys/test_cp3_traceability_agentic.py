"""D18 Phase B CP3 — agentic-path traceability tests.

UI-action → backend-row contracts where an LLM-bearing agent is
in the path. Stronger DB-shape verification than CP1/CP2:

  * Asserts agent_actions row landed.
  * Asserts cost_inr > 0 AND output_data.llm_calls > 0
    (regression guard against BUG-CP1F-shape drift on any new
    agent path).
  * Asserts FK linkage where multiple rows are part of the contract.

Cost class: medium-high (real LLM tests).
"""

from __future__ import annotations

import datetime as _dt
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

pytestmark = [pytest.mark.traceability]


def _setup_entitled_student() -> tuple[_uuid.UUID, str]:
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp3-agentic-{suffix}@example.com"
    password = "Cp3Agentic123!"
    user_id = register_via_http(
        email=email, password=password, full_name="CP3 Agentic Trace",
    )
    token = fetch_token_via_http(email=email, password=password)

    async def _grant(session: AsyncSession) -> None:
        from tests.fixtures.role_state_fixtures import _grant_entitlement as _ge
        await _ge(session, student_id=user_id, course_slug="python-developer")

    mutate_student_state_via_db(_grant)
    return user_id, token


# ── Journey (e) career_coach traceability ──────────────────────────


@pytest.mark.real_llm
@pytest.mark.cost("medium")
def test_career_coach_writes_agent_actions_with_full_cost_tracking(
    page: Page,
) -> None:
    """POST /agentic/default/chat → agent_actions row with full
    cost-tracking shape:
      * student_id = caller's user_id
      * agent_name = the routed agent (career_coach typical)
      * cost_inr > 0 (BUG-CP1F regression guard)
      * output_data.llm_calls >= 1 (token accumulator populated)
      * output_data.input_tokens > 0 + output_tokens > 0
      * status = 'completed'

    HIGH-VALUE traceability: this is the load-bearing CP3 test
    that the BUG-CP1F fix didn't regress. If output_data.llm_calls
    drifts back to 0 on any future v2 agent, this test catches it.
    """
    user_id, token = _setup_entitled_student()
    try:
        before = _dt.datetime.now(_dt.UTC)
        status, body = post_json(
            "/agentic/default/chat",
            token=token,
            body={
                "message": (
                    "I'm a python developer aiming for data analyst. "
                    "What should I focus on next week?"
                ),
            },
            timeout=120,
        )
        assert status == 200
        assert body is not None

        async def _check(session: AsyncSession) -> dict | None:
            r = await session.execute(
                sql_text(
                    """
                    SELECT
                      agent_name,
                      student_id,
                      status,
                      cost_inr::float AS cost_inr,
                      output_data
                    FROM agent_actions
                    WHERE student_id = :sid
                      AND created_at >= :since
                      AND status = 'completed'
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {"sid": user_id, "since": before},
            )
            row = r.one_or_none()
            if not row:
                return None
            return {
                "agent_name": row.agent_name,
                "student_id": row.student_id,
                "status": row.status,
                "cost_inr": float(row.cost_inr) if row.cost_inr else 0.0,
                "output_data": row.output_data or {},
            }

        result = mutate_student_state_via_db(_check)
        assert result is not None, (
            "no completed agent_actions row landed for /agentic/default/chat"
        )

        # Attribution
        assert result["student_id"] == user_id
        assert result["status"] == "completed"

        # The supervisor may dispatch to any agent; just verify
        # SOMETHING handled it (not fallback / supervisor-decline).
        assert result["agent_name"], (
            f"agent_name empty: {result['agent_name']!r}"
        )

        # Cost-tracking shape — BUG-CP1F regression guard
        assert result["cost_inr"] > 0, (
            f"BUG-CP1F regression on agent={result['agent_name']!r}: "
            f"cost_inr={result['cost_inr']} (expected > 0). "
            f"_track_llm_usage may be missing from this agent's run() body."
        )

        # output_data shape — agent's accumulator populated
        od = result["output_data"]
        llm_calls = od.get("llm_calls", 0)
        input_tokens = od.get("input_tokens", 0)
        output_tokens = od.get("output_tokens", 0)
        assert llm_calls >= 1, (
            f"BUG-CP1F regression: llm_calls={llm_calls} for "
            f"agent={result['agent_name']!r}"
        )
        assert input_tokens > 0, (
            f"input_tokens={input_tokens} (accumulator empty?)"
        )
        assert output_tokens > 0, (
            f"output_tokens={output_tokens} (accumulator empty?)"
        )
    finally:
        cleanup_student_via_db(user_id)


# ── Journey (d) mock interview traceability ────────────────────────


@pytest.mark.real_llm
@pytest.mark.cost("high")
def test_mock_session_writes_session_row_and_cost_log_correlated(
    page: Page,
) -> None:
    """Start mock session + submit one answer → traceability chain:
      * interview_sessions row landed with user_id, mode, status='active'
      * mock_cost_log + agent_invocation_log rows correlate by
        session_id (the mock_interview path uses these tables, NOT
        agent_actions — verified via mock_interview_service.py
        which dual-writes to mock_cost_log + agent_invocation_log).
      * cost_inr > 0 across the cost log (regression guard for the
        mock-specific cost-tracking pipeline)

    Pattern 22 finding at CP3 authoring: initial test asserted
    against agent_actions; mock_interview's pipeline writes to
    different tables. Test corrected to pin the actual audit
    contract.
    """
    user_id, token = _setup_entitled_student()
    try:
        before = _dt.datetime.now(_dt.UTC)

        # Start session
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
        assert s_status == 201
        session_id = _uuid.UUID(s_body["session_id"])
        question_id = _uuid.UUID(s_body["first_question"]["id"])

        # Submit one answer
        a_status, _ = post_json(
            f"/mock/sessions/{session_id}/answer",
            token=token,
            body={
                "question_id": str(question_id),
                "text": (
                    "I'd map requirements to existing patterns first, "
                    "then prototype a small slice end-to-end before "
                    "scaling. Validates assumptions cheaply."
                ),
            },
            timeout=120,
        )
        assert a_status == 200

        async def _check(session: AsyncSession) -> dict:
            # interview_sessions side
            sess_row = await session.execute(
                sql_text(
                    """
                    SELECT user_id, mode, status, target_role
                    FROM interview_sessions
                    WHERE id = :sid
                    """
                ),
                {"sid": session_id},
            )
            sess = sess_row.one()

            # mock_cost_log: correlated by session_id (not student_id;
            # the cost log keys on the interview session itself).
            mcl_row = await session.execute(
                sql_text(
                    """
                    SELECT
                      COUNT(*) AS n_rows,
                      MAX(cost_inr)::float AS max_cost,
                      SUM(input_tokens) AS total_in,
                      SUM(output_tokens) AS total_out
                    FROM mock_cost_log
                    WHERE session_id = :sess_id
                    """
                ),
                {"sess_id": session_id},
            )
            mcl = mcl_row.one()

            # agent_invocation_log: dual-write target. user_id +
            # source='mock' filter pins the correct rows.
            ail_row = await session.execute(
                sql_text(
                    """
                    SELECT COUNT(*) AS n_rows,
                           MAX(cost_inr)::float AS max_cost
                    FROM agent_invocation_log
                    WHERE user_id = :uid
                      AND source = 'mock_session'
                      AND created_at >= :since
                    """
                ),
                {"uid": user_id, "since": before},
            )
            ail = ail_row.one()

            return {
                "session_user_id": sess.user_id,
                "session_mode": sess.mode,
                "session_status": sess.status,
                "session_target_role": sess.target_role,
                "mcl_rows": int(mcl.n_rows),
                "mcl_max_cost": float(mcl.max_cost) if mcl.max_cost else 0.0,
                "mcl_total_in": int(mcl.total_in or 0),
                "mcl_total_out": int(mcl.total_out or 0),
                "ail_rows": int(ail.n_rows),
                "ail_max_cost": float(ail.max_cost) if ail.max_cost else 0.0,
            }

        result = mutate_student_state_via_db(_check)

        # interview_sessions contract
        assert result["session_user_id"] == user_id
        assert result["session_mode"] == "behavioral"
        assert result["session_status"] == "active"
        assert result["session_target_role"] == "python-developer"

        # mock_cost_log correlation: each LLM round writes a row;
        # both the question-selection (start) and the answer
        # scoring path emit rows. >= 1 is the contract (>=2 typical).
        assert result["mcl_rows"] >= 1, (
            "no mock_cost_log rows for this session — start+answer "
            "should have written at least one"
        )
        assert result["mcl_max_cost"] > 0, (
            f"mock_cost_log shows zero cost for a real LLM call; "
            f"cost-tracking regression. max_cost={result['mcl_max_cost']}"
        )
        assert result["mcl_total_in"] > 0
        assert result["mcl_total_out"] > 0

        # agent_invocation_log dual-write: the mock service writes
        # here too. Pattern 22 finding at CP3 authoring: source
        # constant is 'mock_session' (verified via
        # backend/app/models/agent_invocation_log.py SOURCE_MOCK
        # = "mock_session"), not 'mock' as initially assumed.
        assert result["ail_rows"] >= 1, (
            "agent_invocation_log dual-write missing for "
            "source='mock_session' — cost-tracking regression "
            "(mock_interview path's dual-write to agent_invocation_log)"
        )
        assert result["ail_max_cost"] > 0
    finally:
        cleanup_student_via_db(user_id)
