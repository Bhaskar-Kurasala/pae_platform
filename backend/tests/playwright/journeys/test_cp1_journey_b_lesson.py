"""D18 Phase B CP1 — Journey (b) lesson nav + completion.

Critical-path tests covering lesson access + completion + state
transition.

Backend-driven (HTTP) for the actual completion mutation; the
CP3 LessonPage's selectors target "Complete lesson" / "Mark
incomplete" but the live frontend renders "Mark as complete" /
"Mark as incomplete" — Pattern 22 / CP3-selector mismatch.
Surfaced as a bug-discovery finding for CP1 closure (see CP1
report's Pattern 22 surfaces section); journey (b) tests use the
HTTP path which is what the assertion contract actually depends
on. The UI selector fix is a small Phase A retrofit that's
deferred until the fix-or-defer call lands.

Cost class: low (no LLM agents invoked).
"""

from __future__ import annotations

import json
import os
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

pytestmark = [pytest.mark.critical_path, pytest.mark.cost("low")]

_API_BASE = os.environ.get("PLAYWRIGHT_API_BASE", "http://nginx/api/v1")


def _http_post(path: str, *, token: str, body: dict | None = None) -> tuple[int, dict | None]:
    """Authed POST; returns (status, parsed body or None)."""
    data = json.dumps(body or {}).encode("utf-8") if body is not None else b"{}"
    req = urllib.request.Request(
        url=f"{_API_BASE}{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:  # type: ignore[name-defined]
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, None


def _http_delete(path: str, *, token: str) -> int:
    req = urllib.request.Request(
        url=f"{_API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="DELETE",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def _http_get(path: str, *, token: str) -> tuple[int, dict | list | None]:
    req = urllib.request.Request(
        url=f"{_API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # type: ignore[name-defined]
        return exc.code, None


def _setup_student_and_lessons(
    n: int = 2,
) -> tuple[_uuid.UUID, str, list[_uuid.UUID]]:
    """Register a student via HTTP, seed n lessons, return (user_id, token, lesson_ids)."""
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp1b-{suffix}@example.com"
    password = "JourneyB123!"
    user_id = register_via_http(
        email=email, password=password, full_name="CP1B Student",
    )
    token = fetch_token_via_http(email=email, password=password)
    chain = seed_student_via_db(
        seed_minimal_lesson_chain,
        course_slug="python-developer",
        n=n,
    )
    return user_id, token, chain.lesson_ids


def _teardown(user_id: _uuid.UUID, lesson_ids: list[_uuid.UUID]) -> None:
    """Best-effort cleanup."""
    cleanup_student_via_db(user_id)

    async def _cleanup_lessons(session: AsyncSession) -> None:
        await cleanup_seeded_lessons(session, lesson_ids=lesson_ids)

    mutate_student_state_via_db(_cleanup_lessons)


# ── Tests ──────────────────────────────────────────────────────────


def test_complete_lesson_creates_progress_row_with_completed_status(
    page: Page,
) -> None:
    """POST /me/lessons/{id}/complete creates student_progress row.

    Pattern 22: assert against actual columns
    (status='completed', completed_at IS NOT NULL).
    """
    user_id, token, lesson_ids = _setup_student_and_lessons(n=1)
    try:
        status, body = _http_post(
            f"/students/me/lessons/{lesson_ids[0]}/complete", token=token,
        )
        assert status == 200, f"complete_lesson returned {status}: {body}"

        async def _check(session: AsyncSession) -> tuple[str, bool]:
            r = await session.execute(
                sql_text(
                    "SELECT status, completed_at IS NOT NULL AS done "
                    "FROM student_progress "
                    "WHERE student_id = :sid AND lesson_id = :lid"
                ),
                {"sid": user_id, "lid": lesson_ids[0]},
            )
            row = r.one()
            return row.status, row.done

        s, completed = mutate_student_state_via_db(_check)
        assert s == "completed"
        assert completed is True
    finally:
        _teardown(user_id, lesson_ids)


def test_uncomplete_lesson_resets_progress_status(page: Page) -> None:
    """DELETE /me/lessons/{id}/complete reverts the student_progress row."""
    user_id, token, lesson_ids = _setup_student_and_lessons(n=1)
    try:
        # Complete first.
        _http_post(
            f"/students/me/lessons/{lesson_ids[0]}/complete", token=token,
        )
        # Then uncomplete.
        status = _http_delete(
            f"/students/me/lessons/{lesson_ids[0]}/complete", token=token,
        )
        assert status == 204

        async def _check(session: AsyncSession) -> str | None:
            r = await session.execute(
                sql_text(
                    "SELECT status FROM student_progress "
                    "WHERE student_id = :sid AND lesson_id = :lid"
                ),
                {"sid": user_id, "lid": lesson_ids[0]},
            )
            row = r.one_or_none()
            return row.status if row else None

        # Status either reverts or row is removed; either is "not completed".
        s = mutate_student_state_via_db(_check)
        assert s != "completed"
    finally:
        _teardown(user_id, lesson_ids)


def test_lesson_get_endpoint_returns_seeded_content(page: Page) -> None:
    """GET /lessons/{id} returns the seeded lesson with expected shape.

    Pattern 22: verify content seeder output is reachable via the
    consumer's API path (not just the table).
    """
    user_id, token, lesson_ids = _setup_student_and_lessons(n=1)
    try:
        status, body = _http_get(f"/lessons/{lesson_ids[0]}", token=token)
        assert status == 200
        assert isinstance(body, dict)
        assert body["id"] == str(lesson_ids[0])
        # Seeder writes "Test lesson <position>" titles starting at order=1000.
        assert body["title"].startswith("Test lesson")
        # Content template includes a marker the seeder embeds.
        assert "test_marker_" in body["content"]
    finally:
        _teardown(user_id, lesson_ids)
