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


def _flush(session: AsyncSession) -> None:
    """No-op kept as documentation hook — see fixture docstrings.

    Originally placeholder for shared post-seed assertion logic;
    retained to mark where future shared invariants would live.
    """
    return


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
