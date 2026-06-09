"""D18 Phase B CP3 — backend-driven traceability tests.

UI-action → backend-row contracts where the load-bearing assertion
is the persisted state, not the UI rendering. CP3-specific
discipline (per saved prompt's CP3.2.c):
  * Read DB state via direct SQL (asyncpg / SA core), not via ORM
    model objects. ORM masks schema drift the way BUG-CP1D was
    masked on dev `platform` DB; raw SQL surfaces drift directly.
  * Assert FK linkage where multiple rows are part of the contract.
  * For agent paths: assert cost_inr > 0 AND llm_calls > 0 (regression
    guard against BUG-CP1F-shape drift on any new path).

Cost class: low (no LLM agents in these tests).
"""

from __future__ import annotations

import datetime as _dt
import uuid as _uuid

import pytest
from playwright.sync_api import Page
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.admin_fixtures import seed_admin_user_with_login
from tests.fixtures.content_seeders import (
    cleanup_seeded_lessons,
    seed_minimal_capstone_bundle,
    seed_minimal_lesson_chain,
)
from tests.fixtures.role_state_fixtures import seed_python_developer_fresh
from tests.playwright.helpers.sync_async_bridge import (
    cleanup_student_via_db,
    fetch_token_via_http,
    mutate_student_state_via_db,
    register_via_http,
    seed_student_via_db,
)

from ._journey_helpers import post_json

pytestmark = [pytest.mark.traceability, pytest.mark.cost("low")]


# ── Journey (a) signup traceability ────────────────────────────────


def test_signup_creates_users_row_and_cohort_event(page: Page) -> None:
    """Signup → users row + cohort_events row (best-effort; the
    auth_service emits cohort_event for role=student).

    Pattern 22 contract pin:
      * users row: must exist with role='student', is_active=true,
        is_verified=false (the default for fresh registrations).
      * cohort_events row: should exist (kind='signup' or
        similar) — best-effort, so test is tolerant if it doesn't
        land but warns. The auth_service wraps the emit in
        try/except per the "Best-effort emit" comment.
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp3a-trace-{suffix}@example.com"
    user_id = register_via_http(
        email=email, password="JourneyA3Trace!", full_name="CP3A Trace",
    )
    try:
        async def _check(session: AsyncSession) -> dict:
            user_row = await session.execute(
                sql_text(
                    "SELECT role, is_active, is_verified, email "
                    "FROM users WHERE id = :id"
                ),
                {"id": user_id},
            )
            u = user_row.one()

            event_count = await session.execute(
                sql_text(
                    "SELECT COUNT(*) FROM cohort_events "
                    "WHERE actor_id = :uid"
                ),
                {"uid": user_id},
            )
            return {
                "role": u.role,
                "is_active": u.is_active,
                "is_verified": u.is_verified,
                "email": u.email,
                "cohort_events": int(event_count.scalar_one()),
            }

        result = mutate_student_state_via_db(_check)
        assert result["role"] == "student"
        assert result["is_active"] is True
        assert result["is_verified"] is False
        assert result["email"] == email
        # cohort_events emit is best-effort; assert >= 0 with a
        # diagnostic message if it didn't land. Hard-asserting > 0
        # would flake if the emit path fails silently (which the
        # service explicitly tolerates).
        # CP3 contract pin: emit fired. If this drifts to 0,
        # admin "Live event feed" loses signup signal.
        assert result["cohort_events"] >= 1, (
            "signup did not emit cohort_event; admin Live event feed "
            "would lose signup signal. Best-effort emit may have failed."
        )
    finally:
        cleanup_student_via_db(user_id)


# ── Journey (b) lesson completion traceability ─────────────────────


def test_complete_lesson_writes_full_progress_row_shape(page: Page) -> None:
    """POST complete_lesson → student_progress row with full shape:
      * status='completed'
      * completed_at IS NOT NULL (Pattern 22 verified)
      * student_id and lesson_id FKs link correctly
      * created_at <= completed_at (temporal contract)
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp3b-trace-{suffix}@example.com"
    user_id = register_via_http(
        email=email, password="JourneyB3Trace!", full_name="CP3B Trace",
    )
    token = fetch_token_via_http(email=email, password="JourneyB3Trace!")
    chain = seed_student_via_db(
        seed_minimal_lesson_chain, course_slug="python-developer", n=1,
    )
    lesson_id = chain.lesson_ids[0]
    try:
        before = _dt.datetime.now(_dt.UTC)
        status, _ = post_json(
            f"/students/me/lessons/{lesson_id}/complete", token=token,
        )
        assert status == 200

        async def _check(session: AsyncSession) -> dict:
            r = await session.execute(
                sql_text(
                    """
                    SELECT student_id, lesson_id, status,
                           completed_at, created_at
                    FROM student_progress
                    WHERE student_id = :sid AND lesson_id = :lid
                    """
                ),
                {"sid": user_id, "lid": lesson_id},
            )
            row = r.one()
            return {
                "student_id": row.student_id,
                "lesson_id": row.lesson_id,
                "status": row.status,
                "completed_at": row.completed_at,
                "created_at": row.created_at,
            }

        result = mutate_student_state_via_db(_check)
        # FK linkage
        assert result["student_id"] == user_id
        assert result["lesson_id"] == lesson_id
        # State
        assert result["status"] == "completed"
        assert result["completed_at"] is not None
        # Temporal contract: completed_at >= before (POST happened)
        assert result["completed_at"] >= before
        # created_at exists and is <= completed_at
        assert result["created_at"] is not None
        assert result["created_at"] <= result["completed_at"]
    finally:
        cleanup_student_via_db(user_id)

        async def _cleanup(session: AsyncSession) -> None:
            await cleanup_seeded_lessons(
                session, lesson_ids=chain.lesson_ids,
            )

        mutate_student_state_via_db(_cleanup)


# ── Journey (c) capstone submission traceability ───────────────────


def test_capstone_submit_writes_row_with_correct_fk_linkage(
    page: Page,
) -> None:
    """POST submit → exercise_submissions row with:
      * student_id FK to users (verified resolvable)
      * exercise_id FK to exercises with is_capstone=TRUE
      * code persisted byte-for-byte
      * status set (one of pending/passed/failed/graded)
      * attempt_number = 1 for first submission
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp3c-trace-{suffix}@example.com"
    user_id = register_via_http(
        email=email, password="JourneyC3Trace!", full_name="CP3C Trace",
    )
    token = fetch_token_via_http(email=email, password="JourneyC3Trace!")
    bundle = seed_student_via_db(
        seed_minimal_capstone_bundle, course_slug="python-developer",
    )

    async def _grant(session: AsyncSession) -> None:
        from tests.fixtures.role_state_fixtures import _grant_entitlement as _ge
        await _ge(session, student_id=user_id, course_slug="python-developer")
    mutate_student_state_via_db(_grant)

    code_payload = (
        "# CP3C traceability test code\n"
        "def solution():\n"
        '    return 42\n'
    )
    try:
        status, body = post_json(
            f"/exercises/{bundle.capstone_exercise_id}/submit",
            token=token,
            body={"code": code_payload},
        )
        assert status == 201

        async def _check(session: AsyncSession) -> dict:
            r = await session.execute(
                sql_text(
                    """
                    SELECT
                      es.student_id,
                      es.exercise_id,
                      es.code,
                      es.status,
                      es.attempt_number,
                      e.is_capstone AS exercise_is_capstone,
                      u.email AS student_email
                    FROM exercise_submissions es
                    JOIN exercises e ON e.id = es.exercise_id
                    JOIN users u ON u.id = es.student_id
                    WHERE es.id = :sub_id
                    """
                ),
                {"sub_id": _uuid.UUID(body["id"])},
            )
            row = r.one()
            return {
                "student_id": row.student_id,
                "exercise_id": row.exercise_id,
                "code": row.code,
                "status": row.status,
                "attempt_number": row.attempt_number,
                "exercise_is_capstone": row.exercise_is_capstone,
                "student_email": row.student_email,
            }

        result = mutate_student_state_via_db(_check)
        # FK linkage resolves end-to-end (JOIN succeeded means both
        # FKs valid)
        assert result["student_id"] == user_id
        assert result["exercise_id"] == bundle.capstone_exercise_id
        assert result["student_email"] == email
        assert result["exercise_is_capstone"] is True
        # Code persisted byte-for-byte
        assert result["code"] == code_payload
        # Status set (CP1 finding: synchronous evaluator may flip
        # from pending; accept the wider set)
        assert result["status"] in (
            "pending", "passed", "failed", "graded",
        )
        # First attempt
        assert result["attempt_number"] == 1
    finally:
        cleanup_student_via_db(user_id)

        async def _cleanup_bundle(session: AsyncSession) -> None:
            await cleanup_seeded_lessons(
                session, lesson_ids=[bundle.lesson_id],
            )

        mutate_student_state_via_db(_cleanup_bundle)


# ── Journey (h) admin DM dual-write traceability ───────────────────


def test_admin_dm_writes_to_student_messages_AND_outreach_log(
    page: Page,
) -> None:
    """POST admin/students/{id}/messages → dual write:
      1. student_messages row with sender_role='admin' + sender_id=admin
      2. outreach_log row with channel='in_app' + triggered_by_user_id=admin

    Per service docstring at student_message_service.py:
      'When admin sends, ALSO writes to outreach_log via F3 so the
      audit trail covers in-app channel as well as email/WA.'

    HIGH-VALUE traceability: silent-failure on the outreach_log mirror
    would make admin DMs invisible to the F3 retention auditor — a
    contract bug Phase B specifically wants to catch.
    """
    admin = seed_student_via_db(seed_admin_user_with_login)
    token = fetch_token_via_http(email=admin.email, password=admin.password)
    student = seed_student_via_db(seed_python_developer_fresh)
    body_text = "CP3H DM traceability — verify dual-write contract"
    try:
        status, post_body = post_json(
            f"/admin/students/{student.user_id}/messages",
            token=token,
            body={"body": body_text},
        )
        assert status == 201, (
            f"admin DM POST failed: status={status} body={post_body}"
        )

        async def _check(session: AsyncSession) -> dict:
            # student_messages side
            sm = await session.execute(
                sql_text(
                    """
                    SELECT student_id, sender_role, sender_id, body
                    FROM student_messages
                    WHERE id = :id
                    """
                ),
                {"id": _uuid.UUID(post_body["id"])},
            )
            sm_row = sm.one()

            # outreach_log mirror — should have channel='in_app',
            # triggered_by_user_id=admin, body_preview matching
            ol = await session.execute(
                sql_text(
                    """
                    SELECT user_id, channel, triggered_by,
                           triggered_by_user_id, body_preview
                    FROM outreach_log
                    WHERE user_id = :sid
                      AND triggered_by_user_id = :aid
                      AND channel = 'in_app'
                    ORDER BY sent_at DESC LIMIT 1
                    """
                ),
                {"sid": student.user_id, "aid": admin.user_id},
            )
            ol_row = ol.one_or_none()

            return {
                "sm": {
                    "student_id": sm_row.student_id,
                    "sender_role": sm_row.sender_role,
                    "sender_id": sm_row.sender_id,
                    "body": sm_row.body,
                },
                "ol": {
                    "user_id": ol_row.user_id if ol_row else None,
                    "channel": ol_row.channel if ol_row else None,
                    "triggered_by": ol_row.triggered_by if ol_row else None,
                    "triggered_by_user_id": ol_row.triggered_by_user_id if ol_row else None,
                    "body_preview": ol_row.body_preview if ol_row else None,
                } if ol_row else None,
            }

        result = mutate_student_state_via_db(_check)

        # student_messages contract
        assert result["sm"]["student_id"] == student.user_id
        assert result["sm"]["sender_role"] == "admin"
        assert result["sm"]["sender_id"] == admin.user_id
        assert result["sm"]["body"] == body_text

        # outreach_log mirror contract — THE CONTRACT BUG GUARD
        assert result["ol"] is not None, (
            "BUG-CP3H-CANDIDATE: admin DM did NOT mirror to "
            "outreach_log via F3. Service docstring promises this "
            "dual-write; the row is missing. Silent-failure on "
            "the mirror means F3 retention auditing loses in-app "
            "channel coverage."
        )
        assert result["ol"]["channel"] == "in_app"
        assert result["ol"]["user_id"] == student.user_id
        assert result["ol"]["triggered_by_user_id"] == admin.user_id
        # Pattern 22 finding at CP3 authoring: the F3 mirror writes
        # triggered_by='admin_manual' (specific source distinguisher),
        # not the generic 'admin' from the architect's edge-inventory
        # framing. Pin the actual value; F3's audit taxonomy uses
        # finer-grained source labels.
        assert result["ol"]["triggered_by"] == "admin_manual"
    finally:
        cleanup_student_via_db(student.user_id)
        cleanup_student_via_db(admin.user_id)


# ── Journey (h) admin trigger_agent traceability (DISC-57) ─────────


def test_admin_trigger_agent_records_full_disc57_attribution(
    page: Page,
) -> None:
    """POST admin/agents/{name}/trigger → agent_actions row with full
    DISC-57 attribution shape:
      * actor_id = admin.id
      * actor_role = 'admin'
      * on_behalf_of = student.id
      * student_id = student.id (the target)
      * agent_name matches the triggered agent

    CP1 verified `actor_role='admin'` and a row landed; CP3 pins the
    full attribution shape including `on_behalf_of` (the field the
    DISC-57 audit explicitly requires for distinguishing
    student-initiated vs admin-initiated agent runs).
    """
    admin = seed_student_via_db(seed_admin_user_with_login)
    token = fetch_token_via_http(email=admin.email, password=admin.password)
    student = seed_student_via_db(seed_python_developer_fresh)
    try:
        before = _dt.datetime.now(_dt.UTC)
        status, _body = post_json(
            "/admin/agents/disrupt_prevention/trigger",
            token=token,
            body={
                "student_id": str(student.user_id),
                "task": "CP3H DISC-57 attribution test",
            },
        )
        # Endpoint may return 200 or 500 depending on whether the
        # disrupt_prevention agent runs cleanly under fresh-student
        # state; the audit row should land regardless (per CP1
        # verification of DISC-57 attribution path).
        assert status in (200, 201, 500)

        async def _check(session: AsyncSession) -> dict | None:
            r = await session.execute(
                sql_text(
                    """
                    SELECT
                      agent_name,
                      student_id,
                      actor_id,
                      actor_role,
                      on_behalf_of
                    FROM agent_actions
                    WHERE student_id = :sid
                      AND actor_id = :aid
                      AND created_at >= :since
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {
                    "sid": student.user_id,
                    "aid": admin.user_id,
                    "since": before,
                },
            )
            row = r.one_or_none()
            if not row:
                return None
            return {
                "agent_name": row.agent_name,
                "student_id": row.student_id,
                "actor_id": row.actor_id,
                "actor_role": row.actor_role,
                "on_behalf_of": row.on_behalf_of,
            }

        result = mutate_student_state_via_db(_check)
        assert result is not None, (
            "trigger_agent did not write agent_actions row with "
            "admin attribution"
        )
        assert result["agent_name"] == "disrupt_prevention"
        assert result["student_id"] == student.user_id
        assert result["actor_id"] == admin.user_id
        assert result["actor_role"] == "admin"
        # DISC-57: on_behalf_of must be set to the target student.
        # If this is None, the audit can't distinguish admin-initiated
        # actions for-this-student from student-initiated.
        assert result["on_behalf_of"] == student.user_id, (
            f"DISC-57 attribution incomplete: on_behalf_of="
            f"{result['on_behalf_of']!r} (expected {student.user_id})"
        )
    finally:
        cleanup_student_via_db(student.user_id)
        cleanup_student_via_db(admin.user_id)
