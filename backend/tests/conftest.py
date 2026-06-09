import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.core.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# ── SQLite ARRAY shim (DISC-SQLite-ARRAY 2026-04-26) ──────────────────────
# `notebook_entries.tags` is `ARRAY(String)` (Postgres-only). The in-memory
# SQLite test DB can't render ARRAY columns and crashes at create_all() with
# `'SQLiteTypeCompiler' object has no attribute 'visit_ARRAY'`. Rather than
# require every test file to monkey-patch around it, register a fallback
# compiler at conftest import time so SQLite renders ARRAY as a JSON column.
@compiles(ARRAY, "sqlite")
def _array_to_json_on_sqlite(_type, _compiler, **_kw):  # type: ignore[no-untyped-def]
    return "JSON"


# ── SQLite JSONB shim (D10 Checkpoint 1, 2026-05-03) ──────────────────────
# Six D1 agentic-OS primitive models (agent_call_chain, agent_escalation,
# agent_memory, agent_proactive_run, agent_tool_call, student_inbox)
# declare columns as `postgresql.JSONB`. SQLite has no JSONB type and
# previously crashed at create_all() with
# `'SQLiteTypeCompiler' object has no attribute 'visit_JSONB'` —
# blocking ~600 tests at fixture-setup time.
#
# Concern C investigation (D10 Checkpoint 1) confirmed zero JSONB
# operators in app code (no ->>, ->, @>, jsonb_*, .astext, .op('->>')
# patterns); every JSONB column is treated as an opaque whole-blob —
# written as a dict, read as a dict, mutated in Python, written back.
# TEXT is the simpler, more portable choice and works on every SQLite
# version without depending on the JSON1 extension. Switch to JSON if
# a future query needs json_extract.
#
# `student_inbox.metadata_` uses `func.cast("{}", JSONB)` as its
# server_default — that goes through SQLAlchemy's compiler at DDL emit
# time, so once JSONB renders as TEXT under SQLite the cast becomes
# `CAST('{}' AS TEXT)` which SQLite accepts cleanly. No model changes
# needed.
#
# See docs/followups/test-suite-sqlite-jsonb-gap.md for the
# investigation report and the residual ARRAY parameter-binding gap
# that this shim does NOT address.
@compiles(JSONB, "sqlite")
def _jsonb_to_text_on_sqlite(_type, _compiler, **_kw):  # type: ignore[no-untyped-def]
    return "TEXT"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


# ── D9 Checkpoint 4 — stub safety gate ─────────────────────────────
#
# The safety primitive (Pass 3g) wraps AgenticBaseAgent.execute() with
# an input + output Presidio scan on every call. Loading Presidio +
# spaCy en_core_web_lg costs ~750MB + ~4s per process; running it
# for every unit test that happens to instantiate an agent would
# slow the suite from ~30s to several minutes AND require Presidio
# to be installed in every test environment.
#
# This autouse fixture replaces the default SafetyGate with a stub
# that returns "allow" for every input and "allow" for every output.
# Tests that specifically exercise the safety contract (the
# test_safety.py file + the test_checkpoint3_integration.py
# safety-wiring tests) opt OUT by clearing the override before
# their own real-Presidio run.


def _is_safety_test(request: pytest.FixtureRequest) -> bool:
    """Return True if the current test specifically exercises safety.

    Two markers:
      • Test file path contains 'test_safety' or 'test_checkpoint3_integration'
        — these tests want the real gate.
      • Test function has @pytest.mark.real_safety_gate.
    """
    path = str(request.node.fspath)
    if "test_safety" in path or "test_checkpoint3_integration" in path:
        return True
    marker = request.node.get_closest_marker("real_safety_gate")
    return marker is not None


@pytest.fixture(autouse=True)
def _stub_safety_gate(request: pytest.FixtureRequest):
    """Replace the default SafetyGate with a stub for non-safety tests.

    The stub:
      - scan_input() → SafetyVerdict(decision="allow")
      - scan_output() → SafetyVerdict(decision="allow")

    Tests that actually want Presidio in the loop (the safety primitive
    test file and the AgenticBaseAgent safety-wiring integration tests)
    skip this fixture via _is_safety_test heuristics.
    """
    if _is_safety_test(request):
        # Real-Presidio test path — let get_default_gate build normally.
        yield
        return

    # Lazy imports so non-agentic tests don't pay the import cost.
    try:
        from app.agents.primitives.safety import gate as _gate_mod
        from app.schemas.safety import SafetyVerdict
    except Exception:
        # Safety module not importable (e.g. minimal CI image) — yield
        # without override; tests proceed normally.
        yield
        return

    class _StubGate:
        """Drop-in replacement for SafetyGate that's always-allow."""

        async def scan_input(self, text, **kwargs):  # type: ignore[no-untyped-def]
            return SafetyVerdict(
                decision="allow",
                findings=[],
                severity_max="info",
                scan_duration_ms=0,
            )

        async def scan_output(self, text, **kwargs):  # type: ignore[no-untyped-def]
            return SafetyVerdict(
                decision="allow",
                findings=[],
                severity_max="info",
                scan_duration_ms=0,
            )

    saved = _gate_mod._default_gate  # type: ignore[attr-defined]
    _gate_mod._default_gate = _StubGate()  # type: ignore[assignment]
    try:
        yield
    finally:
        _gate_mod._default_gate = saved  # type: ignore[assignment]


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(autouse=True)
def _auto_verify_registered_users(monkeypatch: pytest.MonkeyPatch) -> None:
    """Batch 1 test infrastructure: auto-set is_verified=True after every register().

    PURPOSE
    -------
    D-C (login gate) requires is_verified=True before issuing tokens. ~52 test
    helpers do register→login in sequence without a verification step. This
    fixture patches AuthService.register so every test helper's register call
    automatically marks the new user verified in the shared DB session — no
    changes needed in individual test files.

    SCOPE
    -----
    Test environment only. Production AuthService.register is unchanged.
    Autouse ensures every test file gets it without explicit opt-in.

    BYPASS PATTERN (for tests that need an unverified user)
    -------------------------------------------------------
    Tests that specifically need is_verified=False MUST bypass the service
    entirely and create the User directly via ORM:

        user = User(email=..., hashed_password=hash_password(...), is_verified=False)
        db_session.add(user)
        await db_session.flush()

    Do NOT call client.post("/api/v1/auth/register") for unverified-state tests
    — the patch will auto-verify the user before your test can assert on the
    unverified state. See test_auth_token_service.py and test_auth.py for examples.

    PATTERN 35 REFERENCE
    --------------------
    This is test infrastructure, not a workaround. The production login
    state-machine (Pattern 35, N=6) is exercised directly in test_auth.py
    and test_services/test_auth_token_service.py using the ORM bypass path.
    """
    from app.services import auth_service as _auth_svc_mod

    _original_register = _auth_svc_mod.AuthService.register

    async def _patched_register(self, payload):  # type: ignore[no-untyped-def]
        result = await _original_register(self, payload)
        # After registration, mark the user as verified in the shared test session
        # so the subsequent login call in test helpers succeeds.
        try:
            from sqlalchemy import select

            from app.models.user import User

            db_result = await self.repo.db.execute(
                select(User).where(User.email == payload.email)
            )
            user = db_result.scalar_one_or_none()
            if user is not None and not user.is_verified:
                user.is_verified = True
                await self.repo.db.flush()
        except Exception:  # noqa: BLE001
            pass
        return result

    monkeypatch.setattr(_auth_svc_mod.AuthService, "register", _patched_register)


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    """Reset slowapi storage between tests so rate limits don't accumulate.

    Handles both in-memory (dict) and Redis backends.  Redis keys created by
    slowapi follow the pattern ``LIMITER/<ip>/<endpoint>`` so we delete them
    with a wildcard scan.  If Redis is unreachable we fall back silently.
    """
    from app.core.rate_limit import limiter

    # In-memory backend (used when Redis is unavailable)
    storage = getattr(limiter, "_storage", None)
    if storage is not None and hasattr(storage, "storage"):
        inner = getattr(storage, "storage", None)
        if isinstance(inner, dict):
            inner.clear()

    # Redis backend — delete all slowapi limiter keys
    try:
        import redis as redis_lib  # type: ignore[import-untyped]

        from app.core.config import settings

        r = redis_lib.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        keys = r.keys("LIMITS:LIMITER/*")
        if keys:
            r.delete(*keys)
        r.close()
    except Exception:
        # Redis not available in this environment — ignore
        pass


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncClient:
    app.dependency_overrides[get_db] = lambda: db_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Forwarded-For": "127.0.0.1"},
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Batch 1 auth helper ─────────────────────────────────────────────────────
#
# D-B: register now returns 202 (never 201). D-D: password must be ≥12 chars.
# D-C: login is gated on is_verified=True.
#
# All test helpers that previously did register→login with an 8-char password
# now use this fixture-level function. It:
#   1. Registers the user (202).
#   2. Sets is_verified=True on the ORM object via the shared session (same
#      connection as the HTTP client uses, so changes are visible immediately).
#   3. Logs in and returns the access token.
#
# Tests import this via `from tests.conftest import register_and_login` OR use
# the `auth_token` fixture below which provides a pre-authed token string.

_TEST_PASSWORD = "TestPassword123!"  # ≥12 chars, not in common-password list


async def register_and_login(
    client: AsyncClient,
    db_session: AsyncSession,
    email: str = "testuser@example.com",
    full_name: str = "Test User",
    role: str = "student",
    password: str = _TEST_PASSWORD,
) -> str:
    """Register a user, mark them verified, login, return access token."""
    from sqlalchemy import select

    from app.models.user import User

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": full_name, "password": password, "role": role},
    )
    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is not None:
        user.is_verified = True
        await db_session.flush()

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return login_resp.json()["access_token"]


@pytest.fixture
async def auth_token(client: AsyncClient, db_session: AsyncSession) -> str:
    """Fixture: returns an access token for a freshly-registered verified user."""
    return await register_and_login(client, db_session)
