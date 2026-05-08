"""D18 Phase A retrofit-3B smoke — sync_async_bridge.py.

Two smokes covering both axes the bridge is designed for:

  1. DB-seed-then-mutate via the bridge (no browser): exercises
     `seed_student_via_db` + `mutate_student_state_via_db` + the
     thread-isolated asyncpg path.
  2. HTTP-register + bridge-login + browser navigation: exercises
     `register_via_http` + `fetch_token_via_http` +
     `login_as_seeded_student` + a real page navigation.

The two paths are intentionally distinct because Phase A's existing
seed_python_developer_fresh-style fixtures use a placeholder
hashed_password ('x') that cannot authenticate via HTTP. Tests that
need a browser-logged-in student must register via the public
/auth/register endpoint first; tests that need a DB-state-seeded
student (gates, transitions, mock-session signals) without a
browser session can use seed_student_via_db directly.
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.role_state_fixtures import seed_python_developer_fresh
from tests.playwright.helpers.sync_async_bridge import (
    cleanup_student_via_db,
    login_as_seeded_student,
    mutate_student_state_via_db,
    register_via_http,
    seed_student_via_db,
)


def test_seed_student_via_db_lands_real_role_state_row() -> None:
    """seed_student_via_db runs the async role_state_fixtures helper,
    persists the user, and returns a SeededStudent dataclass.

    Verifies via mutate_student_state_via_db (a separate session)
    that the row IS in the backend's connected DB. Catches any
    transaction-scope mistake where the bridge "seeds" but the data
    isn't actually committed.
    """
    student = seed_student_via_db(seed_python_developer_fresh)
    try:
        # Different session (different bridge call) — proves commit landed.
        async def _check(session: AsyncSession) -> tuple[str, bool]:
            row = await session.execute(
                sql_text(
                    "SELECT u.role, "
                    "  s.current_role_id IS NOT NULL AS has_role "
                    "FROM users u LEFT JOIN student_role_state s "
                    "ON u.id = s.student_id "
                    "WHERE u.id = :id"
                ),
                {"id": student.user_id},
            )
            r = row.one()
            return r.role, r.has_role

        role, has_role = mutate_student_state_via_db(_check)
        assert role == "student"
        assert has_role is True
    finally:
        cleanup_student_via_db(student.user_id)


def test_login_as_seeded_student_lands_authed_browser_on_today(
    page: Page,
) -> None:
    """End-to-end via the bridge: register via HTTP, login via the
    bridge's HTTP+localStorage path, navigate, assert the student is
    actually authenticated (not redirected back to /login).

    This is the bridge equivalent of the Phase A CP6 final-loop
    smoke — verifies the bridge's auth injection works against the
    runner overlay's same-origin nginx topology.
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"r3-bridge-smoke-{suffix}@example.com"
    password = "BridgeSmokePass123!"
    full_name = "R3 Bridge Smoke Student"

    user_id = register_via_http(
        email=email, password=password, full_name=full_name,
    )
    try:
        # Inject auth BEFORE navigating — add_init_script applies on
        # subsequent page.goto invocations.
        login_as_seeded_student(
            page,
            user_id=user_id,
            email=email,
            password=password,
            full_name=full_name,
        )
        page.goto("/today")
        # If auth injection failed, frontend's route guard would
        # bounce us to /login. Authed students land on /today (or
        # /onboarding if no goal_contract; either is "authed").
        page.wait_for_url(
            lambda url: "/login" not in url, timeout=15_000,
        )
        landing = page.url
        assert "/today" in landing or "/onboarding" in landing, (
            f"expected authed landing on /today or /onboarding; "
            f"got {landing}"
        )
    finally:
        cleanup_student_via_db(user_id)
