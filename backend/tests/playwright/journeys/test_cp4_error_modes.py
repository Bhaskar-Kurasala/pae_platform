"""D18 Phase B CP4 — error-mode + authorization edges.

Categories per architect's CP4.1.C:
  * Authorization edges (scope: launch-blocking if violated)
  * Concurrency edges (race on shared state)
  * Token-budget edges near boundaries

Pattern 22 finding at CP4 authoring: cross-tenant cohort isolation
is not implemented (no cohort-scoping in admin endpoints) — tests
in that category aren't applicable. Instead, this file pins the
authorization contracts that DO exist:
  * Student endpoints scoped to /me/... (current_user.id) —
    structurally cross-student-safe; tested by API design.
  * Admin endpoints require role='admin' — tested in CP2 already
    via no-token; this file extends with the authed-but-not-admin
    case.
  * Invalid / malformed JWT → 401.

Cost class: low (no LLM agents in this batch).
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
import uuid as _uuid

import pytest
from playwright.sync_api import Page
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.content_seeders import (
    cleanup_seeded_lessons,
    seed_minimal_lesson_chain,
)
from tests.playwright.helpers.sync_async_bridge import (
    cleanup_student_via_db,
    fetch_token_via_http,
    mutate_student_state_via_db,
    register_via_http,
    seed_student_via_db,
)

from ._journey_helpers import API_BASE, get_json, post_json

pytestmark = [pytest.mark.error_state, pytest.mark.cost("low")]


# ── Authorization edges ────────────────────────────────────────────


def test_student_cannot_trigger_admin_agent(page: Page) -> None:
    """Authed student (role='student') hitting /admin/agents/.../trigger
    → 403 Forbidden. Extends CP2's no-token authz check with the
    authed-but-wrong-role case.

    SECURITY-RELEVANT: a 200 here would mean any student can
    impersonate admin actions on themselves or others.
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp4-authz-{suffix}@example.com"
    password = "Cp4Authz123!"
    user_id = register_via_http(
        email=email, password=password, full_name="CP4 Student",
    )
    token = fetch_token_via_http(email=email, password=password)
    try:
        status, body = post_json(
            "/admin/agents/disrupt_prevention/trigger",
            token=token,
            body={
                "student_id": str(user_id),
                "task": "should be rejected — caller is a student",
            },
            timeout=30,
        )
        assert status == 403, (
            f"SECURITY: student-role JWT accepted on admin endpoint; "
            f"status={status} body={body}. _require_admin contract "
            f"broken."
        )
    finally:
        cleanup_student_via_db(user_id)


def test_invalid_jwt_returns_401(page: Page) -> None:
    """Made-up JWT → 401 from any authenticated endpoint."""
    req = urllib.request.Request(
        url=f"{API_BASE}/auth/me",
        headers={
            "Authorization": "Bearer not.a.valid.jwt.token",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            pytest.fail(
                f"SECURITY: invalid JWT accepted; status={resp.status}"
            )
    except urllib.error.HTTPError as exc:
        assert exc.code == 401, (
            f"expected 401 on invalid JWT; got {exc.code}"
        )


def test_no_authorization_header_returns_401(page: Page) -> None:
    """No Authorization header on protected endpoint → 401."""
    req = urllib.request.Request(
        url=f"{API_BASE}/auth/me",
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            pytest.fail(
                f"unauth /auth/me accepted; status={resp.status}"
            )
    except urllib.error.HTTPError as exc:
        assert exc.code == 401


# ── Concurrency: idempotent upsert under parallel writes ──────────


def test_concurrent_lesson_completion_lands_one_progress_row(
    page: Page,
) -> None:
    """Two parallel POSTs to /me/lessons/{id}/complete → one
    student_progress row (upsert semantics under concurrent writes).

    Verifies the
      pg_insert(...).on_conflict_do_update(constraint=...)
    machinery in progress_service handles concurrent INSERTs
    correctly; the unique constraint
    `uq_student_progress_student_lesson` is the contract.

    If two parallel requests produced two rows OR raised an
    IntegrityError that escaped, that's a contract bug.
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp4-conc-{suffix}@example.com"
    password = "Cp4Conc123!"
    user_id = register_via_http(
        email=email, password=password, full_name="CP4 Concurrent",
    )
    token = fetch_token_via_http(email=email, password=password)
    chain = seed_student_via_db(
        seed_minimal_lesson_chain, course_slug="python-developer", n=1,
    )
    lesson_id = chain.lesson_ids[0]
    try:
        # Fire two parallel POSTs from threads.
        results: list[tuple[int, dict | None]] = []
        errors: list[BaseException] = []

        def _hit() -> None:
            try:
                results.append(post_json(
                    f"/students/me/lessons/{lesson_id}/complete",
                    token=token, body={}, timeout=30,
                ))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_hit) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"thread errors: {errors!r}"
        assert len(results) == 2

        # Both should be 200 (idempotent upsert) — neither should
        # have failed with 5xx on a race.
        for status, _body in results:
            assert status == 200, (
                f"parallel completion status={status} (expected 200 "
                f"under upsert semantics)"
            )

        # Exactly one row should exist (unique constraint enforced).
        async def _count(session: AsyncSession) -> int:
            r = await session.execute(
                sql_text(
                    "SELECT COUNT(*) FROM student_progress "
                    "WHERE student_id = :sid AND lesson_id = :lid"
                ),
                {"sid": user_id, "lid": lesson_id},
            )
            return int(r.scalar_one())

        n = mutate_student_state_via_db(_count)
        assert n == 1, (
            f"CONTRACT: unique constraint should produce exactly 1 "
            f"row under concurrent upserts; got {n}"
        )
    finally:
        cleanup_student_via_db(user_id)

        async def _cleanup(session: AsyncSession) -> None:
            await cleanup_seeded_lessons(
                session, lesson_ids=chain.lesson_ids,
            )

        mutate_student_state_via_db(_cleanup)


# ── Error-mode: missing required field ─────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG-CP4-LESSON-FK-500: POST /me/lessons/{nonexistent}/complete "
        "raises ForeignKeyViolationError (asyncpg) which propagates "
        "as an unhandled 500 from FastAPI, instead of a clean 404 "
        "or 422. Surfaced at CP4 authoring 2026-05-09. "
        "Severity: MEDIUM (annoying user-visible 5xx on stale URLs; "
        "not data-corrupting, not security-relevant). "
        "Fix scope: progress_service.complete_lesson should validate "
        "lesson exists OR catch IntegrityError and re-raise as "
        "HTTPException(404). Convention A: xfail-strict; remove "
        "when fix lands. See "
        "docs/followups/bug-cp4-lesson-fk-500.md."
    ),
)
def test_complete_lesson_missing_lesson_id_returns_404_or_422(
    page: Page,
) -> None:
    """POST to /me/lessons/{nonexistent_uuid}/complete → 404 or
    422 (depending on whether the route validator catches the
    missing FK or the service layer does). Either is acceptable;
    a 5xx is not. CURRENTLY: returns 500 (FK violation unhandled)
    — see xfail reason.
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp4-missing-{suffix}@example.com"
    password = "Cp4Missing123!"
    user_id = register_via_http(
        email=email, password=password, full_name="CP4 Missing",
    )
    token = fetch_token_via_http(email=email, password=password)
    try:
        nonexistent_lesson = _uuid.uuid4()
        status, body = post_json(
            f"/students/me/lessons/{nonexistent_lesson}/complete",
            token=token,
            timeout=10,
        )
        assert status in (404, 422, 400), (
            f"expected 4xx for nonexistent lesson; got {status}: {body}"
        )
    finally:
        cleanup_student_via_db(user_id)


# ── Token-budget edge near boundary ────────────────────────────────


@pytest.mark.real_llm
@pytest.mark.cost("medium")
def test_agentic_chat_near_max_length_input_handled_gracefully(
    page: Page,
) -> None:
    """Message at 9_000 chars (under 10_000 max) — valid per
    Pydantic, but stresses the LLM token budget.

    Behavior contract: response is either a substantive answer OR
    a graceful decline (entitlement / token-budget exhaustion);
    not a 500 or empty body.

    Cost is medium — long input means more tokens billed.
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp4-long-{suffix}@example.com"
    password = "Cp4Long123!"
    user_id = register_via_http(
        email=email, password=password, full_name="CP4 Long Input",
    )
    token = fetch_token_via_http(email=email, password=password)

    async def _grant(session: AsyncSession) -> None:
        from tests.fixtures.role_state_fixtures import _grant_entitlement as _ge
        await _ge(session, student_id=user_id, course_slug="python-developer")
    mutate_student_state_via_db(_grant)

    try:
        # 9000 chars of legitimate-looking content (long resume
        # paragraph repeated). Within max_length=10_000.
        chunk = (
            "I'm a python developer with 5 years building data "
            "pipelines, focused on transitioning into AI engineering. "
        )
        long_message = (chunk * (9_000 // len(chunk) + 1))[:9_000]
        status, body = post_json(
            "/agentic/default/chat",
            token=token,
            body={"message": long_message},
            timeout=180,  # long input → longer LLM time
        )
        assert status == 200, (
            f"large valid input returned {status}; expected graceful 200 "
            f"(or graceful 4xx, not 5xx). body={body!r}"
        )
        assert body is not None
        # Either substantive response OR graceful decline:
        response_text = body.get("response", "")
        decline = body.get("decline_reason")
        block = body.get("blocked")
        assert (
            (response_text and len(response_text.strip()) > 0)
            or decline is not None
            or block is True
        ), (
            f"agent returned empty response with no decline/block "
            f"under 9k-char input: body={body!r}"
        )
    finally:
        cleanup_student_via_db(user_id)
