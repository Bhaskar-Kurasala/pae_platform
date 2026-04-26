import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import ARRAY
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


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


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
