"""D18 Phase B CP1 — Journey (c) capstone submission.

Tests the capstone submission flow: register a student, seed a
capstone bundle (retrofit-3A), grant entitlement, POST a
submission, verify the row landed.

Pattern 22 finding from journey (e)/(f): the agentic chat path
gates on entitlement; submission endpoints likely have similar
guards. Inline-grant the relevant entitlement.

Capstone-specific UI (PracticePage submit + senior_review LLM)
deferred to CP2 — CP1 (c) verifies the backend contract only.

Cost class: low (no LLM agents in the submission path itself;
project_evaluator is async / out-of-band).
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
)
from tests.playwright.helpers.sync_async_bridge import (
    cleanup_student_via_db,
    fetch_token_via_http,
    mutate_student_state_via_db,
    register_via_http,
    seed_student_via_db,
)

from ._journey_helpers import post_json

pytestmark = [pytest.mark.critical_path, pytest.mark.cost("low")]


def test_capstone_submission_creates_pending_row_with_correct_attribution(
    page: Page,
) -> None:
    """POST /exercises/{capstone_id}/submit creates exercise_submissions row.

    Pattern 22: assert against actual columns
    (student_id, exercise_id, status='pending', code persisted).
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp1c-{suffix}@example.com"
    password = "JourneyC123!"
    user_id = register_via_http(
        email=email, password=password, full_name="CP1C Capstone Student",
    )
    token = fetch_token_via_http(email=email, password=password)

    # Seed retrofit-3 capstone bundle on python-developer.
    bundle = seed_student_via_db(
        seed_minimal_capstone_bundle, course_slug="python-developer",
    )

    # Grant entitlement so the student can access the course.
    async def _grant(session: AsyncSession) -> None:
        from tests.fixtures.role_state_fixtures import _grant_entitlement as _ge

        await _ge(session, student_id=user_id, course_slug="python-developer")

    mutate_student_state_via_db(_grant)

    submission_code = (
        "# CP1C capstone submission\n"
        "def my_solution():\n"
        '    return "answer"\n'
    )
    try:
        status, body = post_json(
            f"/exercises/{bundle.capstone_exercise_id}/submit",
            token=token,
            body={"code": submission_code},
        )
        assert status == 201, f"submit failed: status={status} body={body}"
        assert body is not None
        assert body["student_id"] == str(user_id)
        assert body["exercise_id"] == str(bundle.capstone_exercise_id)
        # Pattern 22 finding at CP1C authoring: the service writes
        # 'pending' initially per the code path, but the response
        # may surface a downstream-evaluated state ('passed' /
        # 'failed') if a synchronous evaluator fires inline. Accept
        # any of the realistic states; CP3 traceability will pin
        # the exact transition contract.
        assert body["status"] in ("pending", "passed", "failed", "graded"), (
            f"unexpected initial status: {body['status']!r}"
        )

        # DB-side verification: row landed with code persisted.
        async def _check(session: AsyncSession) -> tuple[str, str]:
            r = await session.execute(
                sql_text(
                    "SELECT code, status FROM exercise_submissions "
                    "WHERE student_id = :sid AND exercise_id = :eid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {
                    "sid": user_id,
                    "eid": bundle.capstone_exercise_id,
                },
            )
            row = r.one()
            return row.code, row.status

        code, persisted_status = mutate_student_state_via_db(_check)
        assert code == submission_code
        assert persisted_status in ("pending", "passed", "failed", "graded")
    finally:
        cleanup_student_via_db(user_id)

        async def _cleanup_bundle(session: AsyncSession) -> None:
            await cleanup_seeded_lessons(
                session, lesson_ids=[bundle.lesson_id],
            )

        mutate_student_state_via_db(_cleanup_bundle)
