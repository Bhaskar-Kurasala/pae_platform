"""D18 Phase A CP6 — final end-to-end smoke test.

Full infrastructure stack smoke. Exercises:
  * Page object pattern (LoginPage from CP3)
  * Real auth flow (HTTP register + bcrypt verification)
  * Backend HTTP serving against the connected DB
  * Frontend production build serving + role-based redirect
  * Browser-side localStorage hydration of the auth store

Does NOT invoke any LLM agent. Cost ~₹0.

Failure here means a regression somewhere across CP1-CP5 — the test
is intentionally sensitive to the entire infrastructure surface.

⚠ Network topology requirement ⚠

The frontend's bundle has NEXT_PUBLIC_API_URL baked in at build time.
For browser-side login to actually hit the backend, the frontend
build's API URL must be reachable from the chromium process running
this test. Two supported topologies:

  1. **Host-side execution.** Run pytest from the host, with
     PLAYWRIGHT_BASE_URL=http://localhost:3002 (frontend exposed
     port). The chromium spawned by pytest-playwright lives on the
     host; localhost:8080 (nginx → backend) is reachable. This is
     the workflow CP3 / CP5 smoke have used.
  2. **Overlay (CI).** Run via the playwright-runner service in
     docker-compose.playwright.yml. Frontend rebuild sets
     NEXT_PUBLIC_API_URL to a hostname the runner image can reach
     (typically http://nginx or http://backend:8000).

Running from inside the backend container with
PLAYWRIGHT_BASE_URL=http://frontend:3000 will FAIL these tests
because the chromium process inside the backend container loads
the frontend bundle (which calls localhost:8080) but localhost:8080
inside the backend container is the backend's own port, not
nginx — so the auth/register fetch fails with a network error.

This file's tests are auto-skipped when neither topology is
detected; CI explicitly opts in via the overlay's runner.
"""

from __future__ import annotations

import json
import os
import urllib.request
import uuid as _uuid

import pytest
from playwright.sync_api import Page, expect

from tests.playwright.pages import LoginPage, TodayPage


_API_BASE = os.environ.get("PLAYWRIGHT_API_BASE", "http://nginx/api/v1")


def _frontend_can_reach_backend() -> bool:
    """Detect whether the network topology supports the full loop.

    Returns False when running from inside the backend container with
    PLAYWRIGHT_BASE_URL=http://frontend:3000 (chromium-in-backend-
    container can't reach the host-baked API URL). Returns True when
    PLAYWRIGHT_BASE_URL is a host-accessible URL OR the playwright-
    runner image is in use (env var
    `PLAYWRIGHT_FULL_LOOP_OK=1` set explicitly in
    docker-compose.playwright.yml + the CI workflow).

    The skip is conservative: if we can't prove the topology supports
    the test, skip. Better than a confusing failure trace.
    """
    # CI / overlay: an explicit affirmative env var is the cleanest
    # contract. Set in docker-compose.playwright.yml and the workflow.
    if os.environ.get("PLAYWRIGHT_FULL_LOOP_OK") == "1":
        return True
    # Host-side: PLAYWRIGHT_BASE_URL is localhost-something means
    # chromium runs on the host where localhost:8080 is reachable.
    base = os.environ.get("PLAYWRIGHT_BASE_URL", "")
    if "localhost" in base or "127.0.0.1" in base:
        return True
    return False


pytestmark = pytest.mark.skipif(
    not _frontend_can_reach_backend(),
    reason=(
        "CP6 full loop requires either host-side execution "
        "(PLAYWRIGHT_BASE_URL=http://localhost:3002) or the "
        "playwright-runner overlay (sets PLAYWRIGHT_FULL_LOOP_OK=1). "
        "Running from inside the backend container with "
        "PLAYWRIGHT_BASE_URL=http://frontend:3000 doesn't work because "
        "the frontend bundle's NEXT_PUBLIC_API_URL is baked at build "
        "time and points at localhost:8080, which isn't reachable from "
        "inside the backend container."
    ),
)


def _register_student(*, email: str, password: str, full_name: str) -> _uuid.UUID:
    """Register a fresh student via HTTP. Returns the new user's UUID."""
    req = urllib.request.Request(
        url=f"{_API_BASE}/auth/register",
        data=json.dumps(
            {"email": email, "password": password, "full_name": full_name}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return _uuid.UUID(body["id"])


def _cleanup_student(user_id: _uuid.UUID) -> None:
    """Best-effort teardown via the same thread-isolated asyncpg
    pattern used by the admin fixture. Sync-context-safe."""
    import asyncio
    import threading

    import asyncpg

    backend_db = os.environ.get("PLAYWRIGHT_BACKEND_DB", "platform")

    async def _do() -> None:
        conn = await asyncpg.connect(
            host="db", port=5432, user="postgres", password="postgres",
            database=backend_db,
        )
        try:
            # agent_actions has no CASCADE on student_id; clean explicitly.
            await conn.execute(
                "DELETE FROM agent_actions WHERE student_id = $1", user_id,
            )
            await conn.execute(
                "DELETE FROM users WHERE id = $1", user_id,
            )
        finally:
            await conn.close()

    exc_box: list = []

    def runner() -> None:
        try:
            asyncio.run(_do())
        except BaseException as exc:  # noqa: BLE001
            exc_box.append(exc)

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join()
    # Cleanup is best-effort; raise only in dev mode to surface
    # leaks during test development.
    if exc_box and os.environ.get("PLAYWRIGHT_STRICT_CLEANUP"):
        raise exc_box[0]


def test_full_loop_login_and_today(page: Page) -> None:
    """Full stack smoke: register → login via UI → land on /today.

    Exercises:
      * HTTP register against the backend's connected DB
        (playwright_test under the overlay; platform otherwise).
      * LoginPage.fill_credentials + submit (CP3 page-object pattern).
      * Frontend's role-aware post-login redirect (student → /today).
      * TodayPage.assert_loaded() (CP3 page-object pattern).

    Does NOT exercise:
      * LLM agents (cost protection)
      * Database-level fixtures (CP4 fixture surface; covered in
        the DB-only smoke jobs)
      * Behavior-shape / grounding helpers (CP5 surface; covered
        in test_cp5_helpers.py)

    The four other CP smoke files cover their own surfaces; this is
    the one test where the full stack is exercised end-to-end.
    """
    suffix = _uuid.uuid4().hex[:12]
    email = f"d18-cp6-smoke-{suffix}@example.com"
    password = "SmokeCP6Pass123!"
    full_name = "D18 CP6 Smoke Student"

    user_id = _register_student(
        email=email, password=password, full_name=full_name,
    )
    try:
        login = LoginPage(page)
        login.navigate()
        login.assert_on_login_page()
        login.login(email=email, password=password)

        page.wait_for_url(lambda url: "/login" not in url, timeout=15_000)
        assert page.url.rstrip("/").endswith("/today"), (
            f"expected post-login URL to be /today; got {page.url}"
        )

        today = TodayPage(page)
        today.assert_loaded()
    finally:
        _cleanup_student(user_id)


def test_full_loop_login_invalid_credentials_shows_error(page: Page) -> None:
    """Negative-path full loop: bad credentials → error toast on /login.

    Doesn't seed a user — submits credentials that don't match anyone.
    The frontend's LoginPage form catches the ApiError and renders the
    error div. Regression guard for the auth error path.
    """
    login = LoginPage(page)
    login.navigate()
    login.assert_on_login_page()
    login.login(
        email="nobody-exists-cp6@example.com",
        password="WrongPassword123!",
    )

    # The form error renders inline (not a toast). The backend's
    # auth_service raises HTTPException with detail="Invalid
    # credentials" (verified in CP6 against the live
    # backend/app/services/auth_service.py); the LoginPage form
    # propagates that into the destructive-styled error div via
    # ApiError.message.
    expect(
        page.get_by_text("Invalid credentials", exact=False).first
    ).to_be_visible(timeout=5_000)
    # URL stays on /login (no redirect happened).
    assert "/login" in page.url
