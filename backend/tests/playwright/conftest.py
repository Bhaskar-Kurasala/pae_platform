"""D18 Phase A — Playwright suite root configuration.

Configures pytest-playwright defaults (base URL, viewport, headless,
default timeout) plus (CP2 onward) session-scoped database reset and
function-scoped DB sessions. Subsequent CPs add fixture extensions
(CP4), assertion helpers (CP5), and budget tracking (CP5/CP6).

Two-suite world:
- This suite (Python pytest-playwright at backend/tests/playwright/) drives
  backend-fixture-driven full-stack journeys.
- frontend/e2e/ (TypeScript @playwright/test) drives frontend-team-owned
  UI smoke. Phase B respects the boundary.

The stack must be running before this suite executes (docker compose up -d).
See docs/testing/playwright-setup.md.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_BASE_URL = "http://localhost:3002"
DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
DEFAULT_TIMEOUT_MS = 30_000


def _base_url() -> str:
    return os.environ.get("PLAYWRIGHT_BASE_URL", DEFAULT_BASE_URL)


@pytest.fixture(scope="session")
def base_url() -> str:
    """Override pytest-playwright's default base URL.

    Default targets the docker-compose frontend (host port 3002 per
    README + frontend/CLAUDE.md). Override via PLAYWRIGHT_BASE_URL env
    var (e.g. http://localhost:3000 for `pnpm dev` host workflow, or
    http://frontend:3000 for in-container CI).
    """
    return _base_url()


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    """Desktop-first viewport per D-A scope. Mobile deferred post-launch."""
    return {
        **browser_context_args,
        "viewport": DEFAULT_VIEWPORT,
        "base_url": _base_url(),
    }


def pytest_configure(config: pytest.Config) -> None:
    """Register D18 Phase B test categorization markers.

    Markers also live in backend/pyproject.toml [tool.pytest.ini_options]
    for non-runner pytest invocations, but the runner image's pyproject
    is baked at image-build time. Registering here too means iterative
    test edits don't require a runner image rebuild just to silence
    marker-not-registered warnings.
    """
    config.addinivalue_line(
        "markers",
        "critical_path: CP1 critical-path happy-path journey; runs every PR.",
    )
    config.addinivalue_line(
        "markers",
        "edge_case: CP2 high-value edge-case variant on a critical path.",
    )
    config.addinivalue_line(
        "markers",
        "traceability: CP3 UI action -> backend row verification.",
    )
    config.addinivalue_line(
        "markers",
        "error_state: CP4 error-path coverage.",
    )
    config.addinivalue_line(
        "markers",
        "comprehensive: CP4 nice-to-have coverage; nightly only.",
    )
    config.addinivalue_line(
        "markers",
        "cost: per-test cost class. Use as @pytest.mark.cost('low'|'medium'|'high').",
    )


@pytest.fixture(autouse=True)
def _set_default_timeout(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """30s default per-action timeout for tests that use Playwright's `page`.

    Pure-DB smoke tests (e.g., CP2's test_cp2_db) don't request `page`;
    skip the timeout setup for them so pytest-playwright doesn't
    auto-inject a browser context they don't need. Otherwise every
    pure-DB test parameterizes as `[chromium]` and pays the
    browser-launch cost for nothing.
    """
    if "page" in request.fixturenames:
        page = request.getfixturevalue("page")
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
    yield


# ── CP2: Test database infrastructure ────────────────────────────────
#
# Hybrid DB strategy per D-C:
#   * Suite start: drop+recreate playwright_test from
#     playwright_test_template (cheap; ~1-2s) — once per pytest run.
#   * Per-test: function-scoped AsyncSession bound to playwright_test.
#     Tests use this for fixture seeding + assertions.
#
# The session-scoped reset is the safety net: if a test's teardown
# fails to clean up its data, the next suite run starts clean again
# anyway. Per-test fixture cleanup (CP4) is the primary discipline;
# this is defense in depth.

PLAYWRIGHT_TEST_DB_NAME = "playwright_test"
DEFAULT_ASYNCPG_HOST_PORT = "localhost:5433"
DEFAULT_ASYNCPG_DOCKER_PORT = "db:5432"


def _playwright_test_dsn() -> str:
    """Return the SQLAlchemy/asyncpg DSN for the playwright_test database.

    Honors PLAYWRIGHT_TEST_DSN if set (e.g. CI may override host/port).
    Default heuristic: prefer the docker-network host (`db:5432`) when
    we're running inside a container; fall back to the host-mapped
    port (`localhost:5433`) otherwise. Detection is via the presence
    of /.dockerenv.
    """
    explicit = os.environ.get("PLAYWRIGHT_TEST_DSN")
    if explicit:
        return explicit
    if os.path.exists("/.dockerenv"):
        host_port = DEFAULT_ASYNCPG_DOCKER_PORT
    else:
        host_port = DEFAULT_ASYNCPG_HOST_PORT
    return (
        f"postgresql+asyncpg://postgres:postgres@{host_port}/"
        f"{PLAYWRIGHT_TEST_DB_NAME}"
    )


@pytest.fixture(scope="session")
def playwright_test_dsn() -> str:
    """Expose the test DSN to fixtures + tests that need direct access."""
    return _playwright_test_dsn()


@pytest.fixture(scope="session")
def playwright_db_reset(playwright_test_dsn: str) -> str:
    """Session-scoped: reset playwright_test from the template once per suite.

    Returns the test DSN so dependent fixtures can chain off this one.
    The reset runs the standalone reset_for_suite.py script via
    subprocess so we don't need to manage an event loop here
    (pytest-asyncio's loop hasn't started at session-fixture-setup
    time, and `asyncio.run` would conflict with any test-scope async
    fixtures running later).

    If the template database doesn't exist, the underlying script
    surfaces a clear error pointing at create_template.py rather than
    silently re-running migrations.
    """
    import subprocess
    import sys

    # The reset_for_suite.py script lives next to this conftest in
    # tests/playwright/db/. Resolve via __file__ so the script works
    # regardless of pytest's cwd.
    script = (Path(__file__).parent / "db" / "reset_for_suite.py").resolve()

    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"playwright_db_reset failed (exit {proc.returncode}):\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    # The script prints to stderr; surface in pytest output.
    print(f"\n{proc.stderr.strip()}")
    return playwright_test_dsn


@pytest_asyncio.fixture
async def db_session(
    playwright_db_reset: str,
) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped: one AsyncEngine + AsyncSession per test.

    The engine is created and disposed per-test. asyncpg connections
    bind to the event loop that created them; pytest-asyncio's default
    function-scoped event loop means a session-scoped engine would hit
    "another operation is in progress" / "Event loop is closed" errors
    as connections leak across loops. Per-test engine creation is
    cheap (~50ms) for the small number of smoke tests this targets;
    if CP3+ shows engine-creation cost matters we can switch to
    `loop_scope="session"` and a session-scoped engine in tandem.

    Depends on playwright_db_reset so the suite-level reset runs
    before any test opens a session.
    """
    engine = create_async_engine(playwright_db_reset, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


# ── CP4: per-fixture pytest wrappers ────────────────────────────────
#
# Each pytest fixture below wraps a CP4 seed helper in the
# setup-yield-teardown shape with cleanup_student_data() in teardown.
# The seed helpers in tests/fixtures/* don't commit; these wrappers
# do, so the backend can read the seeded state via its own pool.
#
# Why fixtures live in conftest (not the fixtures package):
#   pytest discovers fixture *functions* via conftest.py only. The
#   seed helpers are reusable building blocks; the pytest-fixture
#   wiring is the discovery surface. If a script needs to call a
#   helper outside pytest, it imports from tests.fixtures directly.
#
# Why one fixture per composite (not a parameterized fixture):
#   Phase B journey tests are scenario-specific by definition;
#   making the scenario explicit in the fixture name is cheaper to
#   read than a parameter. Each composite is ~5 lines of wiring.


@pytest_asyncio.fixture
async def python_developer_student(db_session: AsyncSession) -> AsyncGenerator:
    """Fresh python_developer student, cleaned up after the test."""
    from tests.fixtures.cleanup import cleanup_student_data
    from tests.fixtures.role_state_fixtures import seed_python_developer_fresh

    student = await seed_python_developer_fresh(db_session)
    await db_session.commit()
    yield student
    await cleanup_student_data(db_session, student.user_id)
    await db_session.commit()


@pytest_asyncio.fixture
async def admin_user_with_login(db_session: AsyncSession) -> AsyncGenerator:
    """Admin user with real bcrypt-hashed password (login-capable)."""
    from tests.fixtures.admin_fixtures import seed_admin_user_with_login
    from tests.fixtures.cleanup import cleanup_student_data

    admin = await seed_admin_user_with_login(db_session)
    await db_session.commit()
    yield admin
    await cleanup_student_data(db_session, admin.user_id)
    await db_session.commit()


@pytest_asyncio.fixture
async def paid_silent_student(db_session: AsyncSession) -> AsyncGenerator:
    """Paid 8d ago, silent 12d — paid_silent slip type."""
    from tests.fixtures.cleanup import cleanup_student_data
    from tests.fixtures.journey_fixtures import seed_paid_silent_at_risk_student

    journey = await seed_paid_silent_at_risk_student(db_session)
    await db_session.commit()
    yield journey
    await cleanup_student_data(db_session, journey.student.user_id)
    await db_session.commit()


@pytest_asyncio.fixture
async def capstone_stalled_student(db_session: AsyncSession) -> AsyncGenerator:
    """Entitled, attempted capstone, 15d silent — capstone_stalled slip type."""
    from tests.fixtures.cleanup import cleanup_student_data
    from tests.fixtures.journey_fixtures import seed_capstone_stalled_student

    journey = await seed_capstone_stalled_student(db_session)
    await db_session.commit()
    yield journey
    await cleanup_student_data(db_session, journey.student.user_id)
    await db_session.commit()


@pytest_asyncio.fixture
async def journey_through_data_analyst(db_session: AsyncSession) -> AsyncGenerator:
    """Student fully ready to clear python_developer→data_analyst gate."""
    from tests.fixtures.cleanup import cleanup_student_data
    from tests.fixtures.journey_fixtures import (
        seed_full_journey_through_data_analyst,
    )

    journey = await seed_full_journey_through_data_analyst(db_session)
    await db_session.commit()
    yield journey
    await cleanup_student_data(db_session, journey.student.user_id)
    await db_session.commit()


# ── CP5: budget tracking + admin auth ───────────────────────────────


@pytest.fixture(scope="session")
def budget_tracker():
    """Session-scoped TestBudgetTracker.

    Tests that exercise real-LLM paths request this fixture, capture
    a `start = datetime.now(UTC)` timestamp before the LLM call, and
    after the call:

        cost = await budget_tracker.query_test_cost(db_session, since=start)
        await budget_tracker.record_test_cost(request.node.nodeid, cost)

    `record_test_cost` raises BudgetExceeded if cumulative crosses
    the ceiling (default ₹2.00; override via PLAYWRIGHT_BUDGET_INR).
    pytest fails the test that pushed it over and skips subsequent
    real-LLM tests in the same session.

    Why opt-in (not autouse): pure-DB tests don't generate LLM cost
    and shouldn't pay the query overhead. Autouse hooks would also
    fight the asyncpg/pytest-asyncio loop juggling that CP2/CP3
    already document. CP6 may revisit if a fully-automatic shape
    becomes worth the complexity.
    """
    from tests.playwright.helpers.cost_budget import TestBudgetTracker

    tracker = TestBudgetTracker()
    yield tracker
    # End-of-session report goes to stderr so pytest -v shows it in
    # the run output without needing a custom reporter.
    if tracker.per_test_cost:
        import sys

        print("\n[budget_tracker] " + tracker.report(), file=sys.stderr)


@pytest.fixture
def admin_browser_context(browser, playwright_db_reset):
    """Admin-authenticated Playwright BrowserContext (sync fixture).

    Supersedes the CP3-temporary `pages._helpers.login_as_admin`.

    Why this fixture is SYNC (not @pytest_asyncio.fixture):
      pytest-playwright's sync `page` / `browser` fixtures and
      pytest-asyncio's async fixtures cannot share an event loop
      within a single test — see
      docs/followups/pytest-asyncio-pytest-playwright-split-runs.md.
      Because admin browser tests need to drive Playwright (sync API),
      the supporting auth fixture must also be sync. This means we
      DON'T use the async db_session here; we go through HTTP for
      seed + login, and we depend on `playwright_db_reset` only for
      session ordering (so the template DB exists).

    How admin promotion works without a DB-direct path:
      The public /auth/register endpoint creates a 'student' role.
      We can't promote to admin via HTTP (no admin-promotion endpoint
      exists). For CP5, this fixture seeds via a synchronous psycopg
      connection — `db.host` is the docker-compose service hostname,
      reachable from inside the backend container. This deliberately
      bypasses the SQLAlchemy async engine so we don't fight the
      event-loop ownership.

    Yields (BrowserContext, AdminCredentials) so tests can both
    drive the page AND reference the seeded admin's email.
    """
    import asyncio
    import json
    import os
    import threading
    import urllib.request
    import uuid as _uuid

    import asyncpg

    # ── Strategy: HTTP register + direct UPDATE to admin role ────
    # CP5 admin auth runs against the same database the backend
    # container is connected to. Today that's the dev `platform` DB
    # because the backend's DATABASE_URL points there (Pattern 23
    # finding from CP2). The CP6 docker-compose.playwright.yml
    # overlay will reroute the backend to `playwright_test`; until
    # then, we register an admin via the public /auth/register
    # endpoint (which creates a 'student' role) then UPDATE the
    # role to 'admin' via asyncpg in a thread-isolated loop.
    #
    # The thread isolation is required because pytest-playwright's
    # sync API has an ambient asyncio loop on the main thread that
    # blocks asyncio.run(); running asyncpg in a fresh thread sidesteps
    # that. Documented at the top of
    # docs/followups/pytest-asyncio-pytest-playwright-split-runs.md.
    admin_id = _uuid.uuid4()
    suffix = admin_id.hex[:12]
    email = f"d18-cp5-admin-{suffix}@example.com"
    password = "AdminCP5Pass123!"
    full_name = "D18 CP5 Admin (sync fixture)"

    backend_db = os.environ.get("PLAYWRIGHT_BACKEND_DB", "platform")

    def _run_async(coro_fn):
        result_box: list = []
        exc_box: list = []

        def runner() -> None:
            try:
                result_box.append(asyncio.run(coro_fn()))
            except BaseException as exc:  # noqa: BLE001
                exc_box.append(exc)

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        t.join()
        if exc_box:
            raise exc_box[0]
        return result_box[0] if result_box else None

    # Register via HTTP — creates a 'student' role row.
    register_req = urllib.request.Request(
        url="http://nginx/api/v1/auth/register",
        data=json.dumps(
            {"email": email, "password": password, "full_name": full_name}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(register_req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        admin_id = _uuid.UUID(body["id"])

    # Promote to admin via direct UPDATE on the backend's DB.
    async def _promote() -> None:
        conn = await asyncpg.connect(
            host="db", port=5432, user="postgres", password="postgres",
            database=backend_db,
        )
        try:
            await conn.execute(
                'UPDATE users SET "role" = $1 WHERE id = $2',
                "admin", admin_id,
            )
        finally:
            await conn.close()

    _run_async(_promote)

    # ── HTTP login → JWT ─────────────────────────────────────────
    req = urllib.request.Request(
        url="http://nginx/api/v1/auth/login",
        data=json.dumps({"email": email, "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        token = json.loads(resp.read().decode("utf-8"))["access_token"]

    # ── Browser context + token injection ────────────────────────
    base_url_value = _base_url()
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        base_url=base_url_value,
    )
    # Inject a user object with role=admin so the frontend's
    # admin layout guard (which checks `user?.role === "admin"`)
    # passes. The CP3 student helper got away with user=null
    # because /today doesn't have a role guard, but /admin does.
    encoded_token = json.dumps(token)
    encoded_user = json.dumps(
        {"id": str(admin_id), "email": email, "role": "admin",
         "full_name": full_name, "is_active": True, "is_verified": True}
    )
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

    class _AdminCreds:
        def __init__(self, uid, e, p, n):
            self.user_id = uid
            self.email = e
            self.password = p
            self.full_name = n

    creds = _AdminCreds(admin_id, email, password, full_name)
    try:
        yield context, creds
    finally:
        context.close()

        async def _cleanup() -> None:
            conn = await asyncpg.connect(
                host="db", port=5432, user="postgres", password="postgres",
                database=backend_db,
            )
            try:
                # ON DELETE CASCADE handles most tables;
                # agent_actions.student_id has no CASCADE so explicit.
                await conn.execute(
                    "DELETE FROM agent_actions WHERE student_id = $1",
                    admin_id,
                )
                await conn.execute(
                    "DELETE FROM users WHERE id = $1", admin_id,
                )
            finally:
                await conn.close()

        _run_async(_cleanup)
