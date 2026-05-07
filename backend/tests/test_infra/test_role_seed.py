"""D15 CP1 — live-DB audit of seed + backfill on Postgres.

The model-invariant tests at tests/test_models/test_role_models.py cover
the SQLAlchemy contract under SQLite. These tests cover the *seeded*
state of the Postgres DB after migrations 0061 + 0062 ran:

  * Six roles seeded with correct sequence_order 1-6
  * Only senior_genai_engineer is_terminal=True
  * Five transitions seeded with valid from/to pairs (each connects
    sequential roles)
  * mock_interview_dimensions weights sum to exactly 1.0
  * Per-transition capstone/mock thresholds match the founder seed
  * Every existing user has exactly one student_role_state row
  * Every backfilled student starts at python_developer

Skip if no Postgres reachable — same pattern as
test_sqlite_jsonb_compat.py:_pg_reachable. CI containers without the
db service running pass cleanly; the local dev container + production
asserts are loud.
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _dsn() -> str:
    """Default to the local docker-compose db; override via TEST_PG_DSN."""
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
    reason="No reachable Postgres at TEST_PG_DSN; skip live-DB seed audit.",
)


@pytest.fixture
async def pg_session() -> AsyncSession:
    engine = create_async_engine(_dsn(), echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# ── Seed: roles ───────────────────────────────────────────────────────


async def test_seed_six_roles_with_correct_sequence(
    pg_session: AsyncSession,
) -> None:
    from sqlalchemy import text

    rows = (
        await pg_session.execute(
            text("SELECT slug, sequence_order, is_terminal FROM roles ORDER BY sequence_order")
        )
    ).all()
    assert [(r[0], r[1]) for r in rows] == [
        ("python_developer", 1),
        ("data_analyst", 2),
        ("data_scientist", 3),
        ("ml_engineer", 4),
        ("genai_engineer", 5),
        ("senior_genai_engineer", 6),
    ]
    # Only senior_genai_engineer is terminal.
    terminals = [r[0] for r in rows if r[2] is True]
    assert terminals == ["senior_genai_engineer"]


async def test_seed_role_descriptions_non_empty(
    pg_session: AsyncSession,
) -> None:
    """Identity statements must land — empty descriptions break agent prompts."""
    from sqlalchemy import text

    rows = (
        await pg_session.execute(
            text("SELECT slug, length(description) FROM roles")
        )
    ).all()
    for slug, length in rows:
        # Founder-authored statements run 200-700 chars; pin a loose floor.
        assert length >= 100, f"role {slug} description suspiciously short ({length} chars)"


# ── Seed: transitions ─────────────────────────────────────────────────


async def test_seed_five_transitions_connect_sequential_roles(
    pg_session: AsyncSession,
) -> None:
    from sqlalchemy import text

    rows = (
        await pg_session.execute(
            text(
                """
                SELECT f.sequence_order, t.sequence_order, f.slug, t.slug
                FROM role_transitions rt
                JOIN roles f ON f.id = rt.from_role_id
                JOIN roles t ON t.id = rt.to_role_id
                ORDER BY f.sequence_order
                """
            )
        )
    ).all()

    assert len(rows) == 5
    # Each transition connects sequential roles: (1,2), (2,3), (3,4), (4,5), (5,6).
    for from_order, to_order, _, _ in rows:
        assert to_order == from_order + 1


async def test_seed_transition_thresholds_match_founder_spec(
    pg_session: AsyncSession,
) -> None:
    """Per-transition capstone/mock thresholds match the prompt's table."""
    from sqlalchemy import text

    rows = (
        await pg_session.execute(
            text(
                """
                SELECT
                  f.slug, t.slug,
                  rt.capstone_threshold,
                  rt.capstone_count_required,
                  rt.mock_interview_pass_threshold
                FROM role_transitions rt
                JOIN roles f ON f.id = rt.from_role_id
                JOIN roles t ON t.id = rt.to_role_id
                """
            )
        )
    ).all()
    by_pair = {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}

    expected = {
        ("python_developer", "data_analyst"): (0.65, 1, 0.65),
        ("data_analyst", "data_scientist"): (0.70, 1, 0.70),
        ("data_scientist", "ml_engineer"): (0.72, 1, 0.72),
        ("ml_engineer", "genai_engineer"): (0.75, 1, 0.75),
        ("genai_engineer", "senior_genai_engineer"): (0.80, 2, 0.80),
    }
    assert set(by_pair.keys()) == set(expected.keys())
    for pair, (capstone_t, capstone_n, mock_t) in expected.items():
        actual = by_pair[pair]
        assert actual[0] == pytest.approx(capstone_t, abs=1e-9)
        assert actual[1] == capstone_n
        assert actual[2] == pytest.approx(mock_t, abs=1e-9)


async def test_seed_transition_dimension_weights_sum_to_one(
    pg_session: AsyncSession,
) -> None:
    """Every transition's mock_interview_dimensions weights sum to 1.0."""
    from sqlalchemy import text

    rows = (
        await pg_session.execute(
            text("SELECT mock_interview_dimensions FROM role_transitions")
        )
    ).all()
    assert len(rows) == 5
    for (dims,) in rows:
        assert pytest.approx(sum(dims.values()), abs=1e-9) == 1.0
        assert set(dims.keys()) == {
            "clarity_of_questioning",
            "directional_adherence",
            "complexity_adaptation",
            "technical_correctness",
        }


async def test_seed_transition_window_defaults(
    pg_session: AsyncSession,
) -> None:
    """All transitions use the standard 2-of-last-3 mock window."""
    from sqlalchemy import text

    rows = (
        await pg_session.execute(
            text(
                "SELECT mock_interview_sessions_required_pass, "
                "mock_interview_sessions_window FROM role_transitions"
            )
        )
    ).all()
    assert len(rows) == 5
    for required, window in rows:
        assert (required, window) == (2, 3)


# ── Backfill: student_role_state ──────────────────────────────────────


async def test_backfill_every_user_has_role_state(
    pg_session: AsyncSession,
) -> None:
    """Every user row has exactly one student_role_state row (UNIQUE student_id)."""
    from sqlalchemy import text

    user_count = (
        await pg_session.execute(text("SELECT count(*) FROM users"))
    ).scalar_one()
    srs_count = (
        await pg_session.execute(text("SELECT count(*) FROM student_role_state"))
    ).scalar_one()
    assert srs_count == user_count


async def test_backfill_all_students_start_at_python_developer(
    pg_session: AsyncSession,
) -> None:
    """Backfill semantics: every existing student lands at sequence_order=1."""
    from sqlalchemy import text

    rows = (
        await pg_session.execute(
            text(
                """
                SELECT r.slug, count(*)
                FROM student_role_state s
                JOIN roles r ON r.id = s.current_role_id
                GROUP BY r.slug
                """
            )
        )
    ).all()
    by_slug = {r[0]: r[1] for r in rows}
    # No other role should have any rows yet — the backfill only writes
    # python_developer.
    assert set(by_slug.keys()) == {"python_developer"}
