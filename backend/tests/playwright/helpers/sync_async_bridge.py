"""D18 Phase A retrofit-3B — sync/async bridge for browser tests.

Extracts the inline patterns from CP5's admin_browser_context fixture
and CP1 journey (a)'s test helpers into reusable building blocks.

The fundamental constraint, surfaced repeatedly across CP3 + CP5 + CP6
+ retrofit-1, retrofit-2, retrofit-3:

  pytest-playwright's sync API and pytest-asyncio's async fixtures
  cannot share an event loop within one test. Sync browser tests
  that need to read or mutate the DB must run their async work in a
  fresh thread + asyncio.run, sidestepping the main thread's ambient
  loop.

This module provides:
  * `run_async(coro_factory)` — the canonical thread-isolated runner.
  * `seed_student_via_db(seed_helper, *args, **kwargs)` — runs an
    async role_state_fixtures / journey_fixtures seed helper, opens
    its own asyncpg-via-SQLAlchemy session, commits, returns the
    seeded dataclass.
  * `mutate_student_state_via_db(mutator, *args, **kwargs)` —
    arbitrary async DB work (UPDATE statements, etc.).
  * `login_as_seeded_student(page, *, email, password, role_for_redirect)`
    — completes the HTTP login + browser-side localStorage injection
    that admin_browser_context does inline. Generalized for student
    OR admin paths via `role_for_redirect` (controls the user blob
    injected into auth-storage).

All helpers require the runner overlay topology:
  * `db` service reachable as host=db port=5432 with postgres/postgres
    creds and a database matching `PLAYWRIGHT_BACKEND_DB` env.
  * Backend reachable at `PLAYWRIGHT_API_BASE` env (defaults to
    http://nginx/api/v1).

Usage in a sync browser test:

    from tests.playwright.helpers.sync_async_bridge import (
        run_async, seed_student_via_db, login_as_seeded_student,
    )
    from tests.fixtures.role_state_fixtures import seed_python_developer_fresh

    student = seed_student_via_db(seed_python_developer_fresh)
    # student is a SeededStudent dataclass; user_id, email, etc.
    # ... but the seeded user has a placeholder hashed_password ('x')
    # so it can't log in via HTTP. For login-capable students, use
    # the HTTP register path (see CP1 journey-a `_register_via_http`)
    # or seed_admin_user_with_login from admin_fixtures.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import urllib.request
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from playwright.sync_api import BrowserContext, Page
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

T = TypeVar("T")


_BACKEND_DB = os.environ.get("PLAYWRIGHT_BACKEND_DB", "platform")
_API_BASE = os.environ.get("PLAYWRIGHT_API_BASE", "http://nginx/api/v1")


def _backend_dsn() -> str:
    """SQLAlchemy/asyncpg DSN for the backend's connected DB."""
    return (
        f"postgresql+asyncpg://postgres:postgres@db:5432/{_BACKEND_DB}"
    )


def run_async(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """Run an async coroutine factory in a fresh thread + loop.

    Returns the coroutine's value or re-raises the exception in the
    calling thread. Used by sync Playwright fixtures and tests that
    need to do DB work while the main thread holds pytest-playwright's
    ambient loop.
    """
    result_box: list[T] = []
    exc_box: list[BaseException] = []

    def runner() -> None:
        try:
            result_box.append(asyncio.run(coro_factory()))
        except BaseException as exc:  # noqa: BLE001
            exc_box.append(exc)

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join()
    if exc_box:
        raise exc_box[0]
    return result_box[0]


def seed_student_via_db(
    seed_helper: Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run an async role_state_fixtures / journey_fixtures seed helper.

    Opens an AsyncSession against the backend's connected DB
    (PLAYWRIGHT_BACKEND_DB), invokes `seed_helper(session, *args,
    **kwargs)`, commits, returns the seeded dataclass.

    Caller is responsible for cleanup via mutate_student_state_via_db
    (or the cleanup helpers in tests.fixtures.cleanup) — this bridge
    deliberately doesn't auto-cleanup so callers can compose multiple
    seeds + mutations + assertions in one test.

    Returns whatever seed_helper returns (typically a SeededStudent /
    SeededJourney / SeededAdminWithLogin dataclass).
    """

    async def _do() -> Any:
        engine = create_async_engine(_backend_dsn(), future=True)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                result = await seed_helper(session, *args, **kwargs)
                await session.commit()
                return result
        finally:
            await engine.dispose()

    return run_async(_do)


def mutate_student_state_via_db(
    mutator: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    """Run an arbitrary async mutator with an AsyncSession on the backend DB.

    Use for one-off UPDATE / INSERT / DELETE work that doesn't fit a
    pre-existing seed helper (e.g., flipping a single column,
    inserting an outreach_log row inline, cleaning up a journey).

    Example:
        from sqlalchemy import text as sql_text

        def _flip_to_admin(session):
            return session.execute(
                sql_text("UPDATE users SET role = 'admin' WHERE id = :id"),
                {"id": user_id},
            )
        mutate_student_state_via_db(_flip_to_admin)
    """

    async def _do() -> T:
        engine = create_async_engine(_backend_dsn(), future=True)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                result = await mutator(session)
                await session.commit()
                return result
        finally:
            await engine.dispose()

    return run_async(_do)


def register_via_http(
    *, email: str, password: str, full_name: str
) -> uuid.UUID:
    """Register a user via the public /auth/register endpoint.

    Returns the new user's UUID. Status='student' by default (admin
    promotion is a separate path — see admin_browser_context's
    UPDATE-to-admin step).
    """
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
    return uuid.UUID(body["id"])


def fetch_token_via_http(*, email: str, password: str) -> str:
    """POST /auth/login; return the access_token JWT."""
    req = urllib.request.Request(
        url=f"{_API_BASE}/auth/login",
        data=json.dumps({"email": email, "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    token = body["access_token"]
    if not isinstance(token, str):
        raise RuntimeError(f"login did not return a token; body={body!r}")
    return token


def inject_auth_into_context(
    context: BrowserContext,
    *,
    token: str,
    user_id: uuid.UUID,
    email: str,
    role: str,
    full_name: str = "Test User",
) -> None:
    """Inject the auth token + user blob into a BrowserContext.

    Mirrors admin_browser_context's localStorage injection. The user
    blob is required because route guards on /admin (and potentially
    other role-gated pages) check user.role explicitly — null-user
    fails the guard regardless of isAuthenticated.
    """
    encoded_token = json.dumps(token)
    encoded_user = json.dumps({
        "id": str(user_id),
        "email": email,
        "role": role,
        "full_name": full_name,
        "is_active": True,
        "is_verified": True,
    })
    context.add_init_script(
        f"""(() => {{
            const token = {encoded_token};
            const user = {encoded_user};
            localStorage.setItem("auth_token", token);
            localStorage.setItem("access_token", token);
            localStorage.setItem(
                "auth-storage",
                JSON.stringify({{
                    state: {{
                        user, token, refreshToken: null,
                        isAuthenticated: true,
                    }},
                    version: 0,
                }}),
            );
        }})();"""
    )


def login_as_seeded_student(
    page: Page,
    *,
    user_id: uuid.UUID,
    email: str,
    password: str,
    role: str = "student",
    full_name: str = "Seeded Student",
) -> None:
    """Convenience: HTTP login + page-level auth injection.

    Page-level (not BrowserContext-level) injection so this works for
    tests that take the standard pytest-playwright `page` fixture
    without needing to construct a context manually. For multi-tab
    tests that need context-level scope, use `inject_auth_into_context`
    against `page.context` directly.

    Caller has already created the user (via register_via_http for a
    fresh user, or via seed_admin_user_with_login + DB promotion for
    admin). This helper just logs that existing user into the browser.
    """
    token = fetch_token_via_http(email=email, password=password)
    encoded_token = json.dumps(token)
    encoded_user = json.dumps({
        "id": str(user_id),
        "email": email,
        "role": role,
        "full_name": full_name,
        "is_active": True,
        "is_verified": True,
    })
    page.add_init_script(
        f"""(() => {{
            const token = {encoded_token};
            const user = {encoded_user};
            localStorage.setItem("auth_token", token);
            localStorage.setItem("access_token", token);
            localStorage.setItem(
                "auth-storage",
                JSON.stringify({{
                    state: {{
                        user, token, refreshToken: null,
                        isAuthenticated: true,
                    }},
                    version: 0,
                }}),
            );
        }})();"""
    )


def cleanup_student_via_db(user_id: uuid.UUID) -> None:
    """Delete a student row + their non-CASCADE rows (agent_actions).

    Mirrors the cleanup pattern from CP5 admin_browser_context and
    CP1 journey-a. Best-effort; missing rows no-op.
    """

    async def _do(session: AsyncSession) -> None:
        from sqlalchemy import text as sql_text

        # agent_actions.student_id has no CASCADE — clean explicitly
        # before the user row goes (Pattern 22 verified at CP4).
        await session.execute(
            sql_text("DELETE FROM agent_actions WHERE student_id = :id"),
            {"id": user_id},
        )
        await session.execute(
            sql_text("DELETE FROM users WHERE id = :id"),
            {"id": user_id},
        )

    mutate_student_state_via_db(_do)


__all__ = [
    "cleanup_student_via_db",
    "fetch_token_via_http",
    "inject_auth_into_context",
    "login_as_seeded_student",
    "mutate_student_state_via_db",
    "register_via_http",
    "run_async",
    "seed_student_via_db",
]
