"""D18 Phase A CP3 — Page-object auth helper.

⚠ LEGACY (CP4 update) ⚠
CP4 (2026-05-08) shipped `backend/tests/fixtures/admin_fixtures.py`
with `seed_admin_user_with_login()` returning a real-bcrypt admin
that DOES authenticate via HTTP. The canonical auth path forward is:

    admin = await seed_admin_user_with_login(db_session)
    # ... use admin.email + admin.password with the helpers below
    #     OR a CP5 page-object-side fixture that injects JWT directly.

This module's `login_as_student(page)` is kept for the CP3 smoke
tests that pre-date the CP4 fixture path. `login_as_admin(page)`
goes through the public register endpoint, which silently ignores
role='admin' — the CP3 admin smoke tests remain xfail until CP5
wires up a proper page-object-side admin auth fixture that consumes
seed_admin_user_with_login output.

When CP5 ships the page-object-side admin fixture:
  * Replace `login_as_admin(page)` call sites with the new fixture.
  * Drop the xfail markers on test_admin_cockpit_page_loads and
    test_student_detail_panel_opens.
  * Optionally delete this module if `login_as_student` is also
    superseded.

Mirrors the auth pattern used by frontend/e2e/helpers.ts:
  1. POST /api/v1/auth/register (idempotent: 409 means user already exists)
  2. POST /api/v1/auth/login → {access_token, ...}
  3. page.add_init_script() to inject the token into both
     `localStorage.auth_token` (legacy key) and the Zustand
     `auth-storage` blob (`{state: {token, isAuthenticated: true}}`)
     before any page script runs.

The Zustand-blob shape comes directly from frontend/e2e/helpers.ts
injectAuth() — the frontend reads `state.isAuthenticated` from this
key on hydration and decides whether to redirect to /login.

Why register-then-login (not just login):
  Tests run against a per-suite-clean playwright_test database (see
  CP2 conftest). The smoke users don't exist until we create them.
  Register is idempotent enough — 409 on retry is fine.

Why two users (admin + student):
  CP3 page objects target both portal surfaces (TodayPage, ChatPage,
  LessonPage, MockInterviewPage) and admin surfaces (AdminCockpitPage,
  StudentDetailPanel). Different sessions, different role-based
  landing pages.
"""

from __future__ import annotations

import urllib.error
import urllib.request
import json
from typing import Final

from playwright.sync_api import Page

# Backend reachable at the nginx host port from inside the container
# (docker-compose maps 8080→nginx→backend). For host-run tests the
# default is the same; tests can override via PLAYWRIGHT_API_BASE if
# the topology shifts. Kept short — CP4 fixtures will own the real
# config surface.
API_BASE: Final[str] = "http://nginx/api/v1"

# Smoke users authored at CP3 time. Stable across runs — registration
# is idempotent. CP4 fixture-based auth replaces these with per-test
# scoped users so cross-test interference is structurally impossible.
# Pydantic's email-validator rejects reserved TLDs (.local, .test,
# .invalid). Use a real-looking domain — these are fictitious and
# never resolved by anything outside the pytest user table.
ADMIN_EMAIL: Final[str] = "cp3-smoke-admin@example.com"
ADMIN_PASSWORD: Final[str] = "SmokeAdmin123!"
STUDENT_EMAIL: Final[str] = "cp3-smoke-student@example.com"
STUDENT_PASSWORD: Final[str] = "SmokeStudent123!"


def _post_json(path: str, body: dict[str, object]) -> tuple[int, dict[str, object]]:
    """POST JSON to API_BASE+path; return (status, parsed body or {}).

    Uses urllib instead of httpx so this helper has zero new deps; the
    suite already pulls Playwright but doesn't need an HTTP client for
    the auth side-channel.
    """
    req = urllib.request.Request(
        url=f"{API_BASE}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            payload = {}
        return exc.code, payload


def _ensure_user(email: str, password: str, *, full_name: str, role: str | None) -> None:
    """Register the user idempotently. 409 (already exists) is fine.

    `role` may be None (default student); admin promotion is handled
    via a separate path in CP4 fixtures. CP3 admin surfaces are tested
    against an admin user that the suite seeds via the playwright_test
    template's admin promotion contract — NOT here.

    NOTE: At CP3 time we do not promote to admin from this helper. The
    CP3 admin smoke test is gated on having an admin user available;
    if the playwright_test database doesn't yet seed an admin (CP4
    fixtures will), the admin smoke is marked xfail. See
    test_cp3_pages.py for the gating.
    """
    body: dict[str, object] = {
        "email": email,
        "password": password,
        "full_name": full_name,
    }
    if role:
        body["role"] = role
    _post_json("/auth/register", body)


def _fetch_token(email: str, password: str) -> str:
    status, payload = _post_json(
        "/auth/login", {"email": email, "password": password}
    )
    if status != 200 or "access_token" not in payload:
        raise RuntimeError(
            f"login failed for {email!r}: status={status} body={payload!r}"
        )
    token = payload["access_token"]
    assert isinstance(token, str)
    return token


def _inject_token(page: Page, token: str) -> None:
    """Inject `token` into localStorage so the Zustand auth store hydrates authed.

    Mirrors frontend/e2e/helpers.ts injectAuth() — both legacy and
    new key shapes are written so future store refactors don't silently
    log the user out.
    """
    # sync API's add_init_script doesn't accept an arg parameter the way
    # the async API does — bake the token into the script string. Token
    # is JWT (no quotes / no special chars), so JSON-encoding it is
    # safe and explicit.
    encoded = json.dumps(token)
    page.add_init_script(
        script=f"""(() => {{
            const token = {encoded};
            localStorage.setItem("auth_token", token);
            localStorage.setItem("access_token", token);
            const existing = localStorage.getItem("auth-storage");
            if (existing) {{
                try {{
                    const parsed = JSON.parse(existing);
                    if (parsed.state && parsed.state.isAuthenticated) return;
                }} catch (e) {{}}
            }}
            localStorage.setItem(
                "auth-storage",
                JSON.stringify({{
                    state: {{
                        user: null,
                        token,
                        refreshToken: null,
                        isAuthenticated: true,
                    }},
                    version: 0,
                }}),
            );
        }})();"""
    )


def login_as_student(page: Page) -> None:
    """Authenticate `page` as the CP3 smoke student user.

    Idempotent: registration is best-effort (409s ignored), login
    re-issues a fresh token each call.

    ⚠ CP4 supersedes ⚠
    """
    _ensure_user(STUDENT_EMAIL, STUDENT_PASSWORD, full_name="CP3 Smoke Student", role=None)
    token = _fetch_token(STUDENT_EMAIL, STUDENT_PASSWORD)
    _inject_token(page, token)


# login_as_admin retired at CP5. The page-object-side admin auth
# fixture `admin_browser_context` (in playwright/conftest.py) is
# the canonical path. It composes register-via-HTTP + role
# promotion via asyncpg + token+user injection, and yields a
# (BrowserContext, AdminCredentials) tuple. CP3 admin smoke tests
# now use it directly and pass without xfail markers.
