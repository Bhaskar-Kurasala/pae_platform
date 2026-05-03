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
