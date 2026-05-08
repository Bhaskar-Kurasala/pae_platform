"""D18 Phase B CP1 — Journey (f) resume_reviewer regression guard.

Per architect's Q1 directive (option 3): regression guard verifying:
  1. handoff_request IS NULL (the Option-B defense-in-depth contract)
  2. Substantive output is non-empty (the supervisor-orchestrated
     path returns a synthesized answer; we assert that's a real
     resume-review-shaped response).
  3. Cost tracking populates agent_invocation_log / agent_actions.
     ⚠ Surfaced bug at CP1F authoring: agent_actions.cost_inr = 0.0
     and output_data.llm_calls = 0 despite a real LLM call landing.
     Per Convention A: xfailed with strict=True until investigated.
     See CP1 closure for ticket reference.

This is the only Phase B test for journey (f) — the mandatory chain
itself is intentionally deferred per `resume_reviewer_v2.py`
docstring ("Defense-in-depth: Option B — never ship populated
handoff_request").

Cost class: medium (one real LLM call ~₹2).
"""

from __future__ import annotations

import datetime as _dt
import os
import uuid as _uuid

import pytest
from playwright.sync_api import Page
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.role_state_fixtures import seed_python_developer_fresh
from tests.playwright.helpers.sync_async_bridge import (
    cleanup_student_via_db,
    fetch_token_via_http,
    mutate_student_state_via_db,
    register_via_http,
    seed_student_via_db,
)

from ._journey_helpers import post_json

pytestmark = [pytest.mark.critical_path, pytest.mark.cost("medium")]


_SAMPLE_RESUME = """
Jane Smith
Senior Software Engineer · jane@example.com

EXPERIENCE
Acme Corp — Senior Engineer · 2022-Present
  - Led migration of monolith to microservices (40% latency reduction)
  - Mentored 4 junior engineers; ran weekly code reviews

WidgetCo — Software Engineer · 2019-2022
  - Built customer dashboard serving 100K MAU on React + Node

SKILLS
Python, TypeScript, AWS, PostgreSQL, Docker, Kubernetes

EDUCATION
B.S. Computer Science, State University, 2019
"""


def _invoke_resume_reviewer(page: Page) -> tuple[_uuid.UUID, dict]:
    """Shared setup: register + entitle + invoke + return (user_id, agent_actions row).

    Caller is responsible for cleanup_student_via_db(user_id).
    Returns the agent_actions row (with output_data + cost_inr).
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp1f-{suffix}@example.com"
    password = "JourneyF123!"
    full_name = "CP1F Resume Subject"
    user_id = register_via_http(
        email=email, password=password, full_name=full_name,
    )
    token = fetch_token_via_http(email=email, password=password)

    async def _grant(session: AsyncSession) -> None:
        from tests.fixtures.role_state_fixtures import _grant_entitlement as _ge

        await _ge(session, student_id=user_id, course_slug="python-developer")

    mutate_student_state_via_db(_grant)

    before = _dt.datetime.now(_dt.UTC)
    framed_message = (
        "Please review my resume and tell me where to improve "
        "for a senior engineering role:\n\n" + _SAMPLE_RESUME
    )
    status, body = post_json(
        "/agentic/default/chat",
        token=token,
        body={"message": framed_message},
        timeout=120,
    )
    assert status == 200, f"chat failed: status={status} body={body}"
    assert body is not None, "expected response body"
    assert body.get("agent_name") == "resume_reviewer", (
        f"expected supervisor to route to resume_reviewer, "
        f"got agent_name={body.get('agent_name')!r}"
    )

    async def _check(session: AsyncSession) -> dict:
        r = await session.execute(
            sql_text(
                """
                SELECT output_data, cost_inr
                FROM agent_actions
                WHERE student_id = :sid
                  AND agent_name = 'resume_reviewer'
                  AND created_at >= :since
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"sid": user_id, "since": before},
        )
        row = r.one_or_none()
        if not row:
            return {}
        return {
            "output_data": row.output_data,
            "cost_inr": float(row.cost_inr) if row.cost_inr else 0.0,
        }

    record = mutate_student_state_via_db(_check)
    assert record, "expected agent_actions row for resume_reviewer"
    return user_id, record


@pytest.mark.real_llm
def test_resume_reviewer_enforces_handoff_request_none_and_substantive_output(
    page: Page,
) -> None:
    """Single critical-path regression test for resume_reviewer_v2.

    Pattern 22: assert against the actual ResumeReviewerOutput
    shape (handoff_request field exists; overall_score 0-100;
    list fields default to []).

    The agentic path requires an active entitlement (Pattern 22
    surface at CP1F: /agentic/default/chat returns 402
    no_active_entitlement for fresh students). Inline-grant
    python-developer entitlement before invoking.
    """
    user_id, record = _invoke_resume_reviewer(page)
    try:
        # agent_actions.output_data wraps the agent's structured
        # payload under `output_preview`. Top-level keys are LLM
        # bookkeeping (llm, llm_calls, input_tokens, output_tokens).
        output_data = record["output_data"] or {}
        agent_payload = output_data.get("output_preview") or {}

        # ── Regression guard #1 — THE journey-(f) point ───────
        # handoff_request is None / null. Option-B defense-in-depth.
        handoff = agent_payload.get("handoff_request")
        assert handoff is None, (
            f"resume_reviewer violated Option-B contract: "
            f"handoff_request={handoff!r} (expected None)"
        )

        # ── Regression guard #2 — substantive output ───────────
        # Synthesized answer must be a real resume review.
        answer = agent_payload.get("answer", "")
        assert answer and len(answer.strip()) > 50, (
            f"answer empty/too short: {answer!r}"
        )
        assert "score" in answer.lower() or "resume" in answer.lower(), (
            f"answer doesn't read like a resume review: {answer[:200]!r}"
        )
    finally:
        cleanup_student_via_db(user_id)


@pytest.mark.real_llm
@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG-CP1F-COST-TRACKING: agent_actions.cost_inr = 0.0 + "
        "output_data.llm_calls = 0 for a real LLM call via "
        "/agentic/default/chat. Synthesized answer landed (real "
        "LLM ran) but cost-tracking pipeline reports zero. "
        "Surfaced at CP1F authoring 2026-05-09. Adjacent to D17b "
        "ITEM 1 cost-tracking fix; does not block journey (f)'s "
        "primary regression guard. Convention A: xfail strict=True; "
        "drop xfail when fix lands."
    ),
)
def test_resume_reviewer_records_cost_inr_for_real_llm_call(
    page: Page,
) -> None:
    """Cost-tracking regression test (D17b ITEM 1 contract).

    Per the saved D17b context, cost_inr should populate
    unconditionally on every HTTP agent path (CP4 pre-flight verified
    this for the agent_invocation_log table). This test asserts the
    same contract for agent_actions.cost_inr on the supervisor-
    orchestrated `/agentic/default/chat` path.

    Currently xfailed-strict because the call returns cost_inr=0.0
    even when a real LLM ran (synthesized answer landed; just no
    cost recorded). When fix lands, drop the xfail.
    """
    user_id, record = _invoke_resume_reviewer(page)
    try:
        assert record["cost_inr"] > 0, (
            f"agent_actions.cost_inr should be > 0 for real LLM call; "
            f"got {record['cost_inr']}"
        )
    finally:
        cleanup_student_via_db(user_id)
