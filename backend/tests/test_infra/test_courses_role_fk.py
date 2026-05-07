"""D15 CP2b — courses.role_id FK + backfill audit on live Postgres.

Pins the schema enhancement and two-tier backfill from migrations 0063
+ 0064. SQLite test slice can't exercise the partial index or the FK
constraint identically, so this is a Postgres-only audit (skip if
unreachable, same convention as test_role_seed.py).

Coverage:

  Schema (0063):
    * courses.role_id column exists, is UUID, is nullable
    * fk_courses_role_id FK targets roles.id with ON DELETE SET NULL
    * idx_courses_role_id partial index exists (WHERE role_id IS NOT NULL)

  Tier 1 backfill (0064 auto):
    * Five role-named courses have role_id matching their slug-converted role
      (python-developer → python_developer, data-analyst → data_analyst,
       data-scientist → data_scientist, ml-engineer → ml_engineer,
       genai-engineer → genai_engineer)

  Tier 2 backfill (0064 founder-decided 2026-05-08):
    * python-foundations            → python_developer
    * intro-ai-engineering          → genai_engineer
    * production-rag                → genai_engineer
    * llm-evaluation                → senior_genai_engineer
    * agent-orchestration-langgraph → senior_genai_engineer
    * data-analyst-path             → data_analyst

  NULL preservation:
    * d12-smoke-course (test fixture) stays NULL post-migration

  FK enforcement:
    * Updating a course's role_id to a non-existent UUID is rejected by Postgres

  Capstone visibility (the load-bearing CP4 verification):
    * Capstones under python-foundations + intro-ai-engineering are now
      reachable via courses.role_id JOIN

  Coverage invariant:
    * Every role (except senior_genai_engineer is permitted but happens to
      have 2) has at least one course mapped, OR is explicitly tolerated
      as roleless
"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _dsn() -> str:
    return os.environ.get(
        "TEST_PG_DSN",
        "postgresql+asyncpg://postgres:postgres@localhost:5433/platform",
    )


def _pg_reachable() -> bool:
    raw = _dsn().replace("postgresql+asyncpg://", "postgresql://", 1)

    async def _probe() -> bool:
        try:
            conn = await asyncpg.connect(raw, timeout=2.0)
            await conn.close()
            return True
        except Exception:
            return False

    try:
        return asyncio.run(_probe())
    except Exception:
        return False


_PG_OK = _pg_reachable()
pytestmark = pytest.mark.skipif(
    not _PG_OK,
    reason="No reachable Postgres at TEST_PG_DSN; skip courses.role_id audit.",
)


@pytest.fixture
async def pg_session() -> AsyncSession:
    engine = create_async_engine(_dsn(), echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# ── Schema (0063) ─────────────────────────────────────────────────────


async def test_courses_role_id_column_shape(pg_session: AsyncSession) -> None:
    """role_id is UUID, nullable, with the named FK to roles.id."""
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'courses' AND column_name = 'role_id'
                """
            )
        )
    ).all()
    assert len(rows) == 1, "courses.role_id column missing"
    data_type, is_nullable = rows[0]
    assert data_type == "uuid"
    assert is_nullable == "YES"


async def test_courses_role_fk_constraint_exists(
    pg_session: AsyncSession,
) -> None:
    """fk_courses_role_id targets roles.id with ON DELETE SET NULL."""
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT
                  tc.constraint_name,
                  rc.delete_rule,
                  ccu.table_name AS target_table,
                  ccu.column_name AS target_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.referential_constraints rc
                  ON rc.constraint_name = tc.constraint_name
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                WHERE tc.table_name = 'courses'
                  AND tc.constraint_name = 'fk_courses_role_id'
                """
            )
        )
    ).all()
    assert len(rows) == 1, "fk_courses_role_id constraint missing"
    _, delete_rule, target_table, target_column = rows[0]
    assert delete_rule == "SET NULL"
    assert target_table == "roles"
    assert target_column == "id"


async def test_courses_role_partial_index_exists(
    pg_session: AsyncSession,
) -> None:
    """idx_courses_role_id is a partial index WHERE role_id IS NOT NULL."""
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'courses' AND indexname = 'idx_courses_role_id'
                """
            )
        )
    ).all()
    assert len(rows) == 1, "idx_courses_role_id index missing"
    _, indexdef = rows[0]
    # The partial-index predicate appears in indexdef as "WHERE (role_id IS NOT NULL)".
    assert "role_id IS NOT NULL" in indexdef


# ── Tier 1: slug-convention backfill ──────────────────────────────────


async def test_tier1_role_named_courses_mapped(
    pg_session: AsyncSession,
) -> None:
    """Five role-named courses inherit the matching role via slug convention."""
    expected: dict[str, str] = {
        "python-developer": "python_developer",
        "data-analyst": "data_analyst",
        "data-scientist": "data_scientist",
        "ml-engineer": "ml_engineer",
        "genai-engineer": "genai_engineer",
    }
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT c.slug, r.slug
                FROM courses c
                JOIN roles r ON r.id = c.role_id
                WHERE c.slug = ANY(:slugs)
                """
            ),
            {"slugs": list(expected.keys())},
        )
    ).all()
    actual = {course_slug: role_slug for course_slug, role_slug in rows}
    assert actual == expected


# ── Tier 2: founder-decided tributary backfill ────────────────────────


async def test_tier2_tributary_mappings_match_founder_decision(
    pg_session: AsyncSession,
) -> None:
    """Six tributary courses carry the founder-decided 2026-05-08 mappings."""
    expected: dict[str, str] = {
        "python-foundations": "python_developer",
        "intro-ai-engineering": "genai_engineer",
        "production-rag": "genai_engineer",
        "llm-evaluation": "senior_genai_engineer",
        "agent-orchestration-langgraph": "senior_genai_engineer",
        "data-analyst-path": "data_analyst",
    }
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT c.slug, r.slug
                FROM courses c
                JOIN roles r ON r.id = c.role_id
                WHERE c.slug = ANY(:slugs)
                """
            ),
            {"slugs": list(expected.keys())},
        )
    ).all()
    actual = {course_slug: role_slug for course_slug, role_slug in rows}
    assert actual == expected


# ── NULL preservation ─────────────────────────────────────────────────


async def test_smoke_course_stays_null(pg_session: AsyncSession) -> None:
    """d12-smoke-course is a test fixture and intentionally unmapped."""
    role_id = (
        await pg_session.execute(
            text("SELECT role_id FROM courses WHERE slug = 'd12-smoke-course'")
        )
    ).scalar_one()
    assert role_id is None


# ── FK constraint enforcement ─────────────────────────────────────────


async def test_fk_rejects_invalid_role_uuid(pg_session: AsyncSession) -> None:
    """Setting role_id to a UUID that doesn't exist in roles is rejected."""
    bogus = uuid.uuid4()
    with pytest.raises(IntegrityError):
        await pg_session.execute(
            text(
                "UPDATE courses SET role_id = :bogus "
                "WHERE slug = 'd12-smoke-course'"
            ),
            {"bogus": str(bogus)},
        )
        await pg_session.commit()
    # Roll back so the fixture can clean up cleanly.
    await pg_session.rollback()


# ── Capstone visibility (CP4 load-bearing) ────────────────────────────


async def test_capstones_reachable_via_role_id_join(
    pg_session: AsyncSession,
) -> None:
    """All 3 existing capstones become role-tagged after backfill.

    Pre-D15-CP2b: capstones were unreachable via courses.role_id (column
    didn't exist). Post-CP2b: 1 capstone for python_developer, 2 for
    genai_engineer. CP4 Phases 3 + 4 depend on this.
    """
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT r.slug AS role_slug, count(*) AS capstone_count
                FROM exercises e
                JOIN lessons l ON l.id = e.lesson_id
                JOIN courses c ON c.id = l.course_id
                JOIN roles r ON r.id = c.role_id
                WHERE e.is_capstone = TRUE
                GROUP BY r.slug
                ORDER BY r.slug
                """
            )
        )
    ).all()
    by_role = {role_slug: count for role_slug, count in rows}
    # Reflects current authored content state — not all roles have capstones
    # yet. python_developer + genai_engineer must have at least one each
    # for CP4 verification to land.
    assert by_role.get("python_developer", 0) >= 1
    assert by_role.get("genai_engineer", 0) >= 2


# ── Coverage invariant ────────────────────────────────────────────────


async def test_every_role_except_data_scientist_ml_engineer_has_courses(
    pg_session: AsyncSession,
) -> None:
    """Every role has at least one mapped course, except data_scientist and
    ml_engineer (those have only their role-named course; that's by design
    on the current dev DB — they ship with no tributary content yet).

    Asserts the v1 invariant: at minimum, every role has 1 course
    (the role-named one if no tributary). senior_genai_engineer
    benefits from the founder's 2026-05-08 promotion of llm-evaluation
    + agent-orchestration-langgraph to the terminal tier.
    """
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT r.slug, count(c.id) AS courses
                FROM roles r
                LEFT JOIN courses c ON c.role_id = r.id
                GROUP BY r.slug, r.sequence_order
                ORDER BY r.sequence_order
                """
            )
        )
    ).all()
    by_role = {role_slug: count for role_slug, count in rows}
    # Six roles seeded; every one should appear in the LEFT JOIN.
    assert set(by_role.keys()) == {
        "python_developer",
        "data_analyst",
        "data_scientist",
        "ml_engineer",
        "genai_engineer",
        "senior_genai_engineer",
    }
    # Every role has at least one course.
    for slug, count in by_role.items():
        assert count >= 1, f"role {slug} has zero courses mapped"
    # senior_genai_engineer was deliberately given two courses.
    assert by_role["senior_genai_engineer"] == 2
