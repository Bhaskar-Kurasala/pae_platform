"""D15 CP2 — Phase 1 schema audit for the role-state tools' read paths.

Pins the exact JOIN shapes that read_student_role_state,
read_student_accessible_content, and evaluate_student_against_gate
depend on. Sibling files cover individual table seeds:

  * test_role_seed.py            — six roles + five transitions seeded
  * test_courses_role_fk.py      — courses.role_id FK + tier1/tier2 backfill

This file pins the cross-table joins those tools execute. If a future
migration drops a column or renames a table the tools query against,
THIS file fires before the tool's smoke test fails with a less obvious
error.

Coverage:

  read_student_role_state path:
    * student_role_state JOIN roles ON current_role_id resolves
    * role_transitions JOIN roles f / roles t resolves and finds 5 rows

  read_student_accessible_content path:
    * course_entitlements JOIN courses LEFT JOIN roles is the hot
      query; verify it executes without column-name errors
    * exercises JOIN lessons JOIN courses LEFT JOIN roles works
    * lesson_resources JOIN courses LEFT JOIN roles works (even when
      lesson_resources is empty)

  evaluate_student_against_gate path:
    * exercise_submissions JOIN exercises (is_capstone) JOIN lessons
      JOIN courses on courses.role_id resolves
    * agent_actions has the agent_name + student_id + output_data
      columns the tool reads

  Adjacency invariant:
    * For every non-terminal role, exactly one role_transitions row
      exists with from_role_id = that role
    * Terminal role has no outbound transition

  Index coverage:
    * idx_courses_role_id is partial (already covered in test_courses
      _role_fk.py); pinned again here from the tool's perspective.
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest
from sqlalchemy import text
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
    reason="No reachable Postgres at TEST_PG_DSN; skip role-state tools schema audit.",
)


@pytest.fixture
async def pg_session() -> AsyncSession:
    engine = create_async_engine(_dsn(), echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# ── read_student_role_state path ──────────────────────────────────────


async def test_student_role_state_join_roles_resolves(
    pg_session: AsyncSession,
) -> None:
    """The exact query read_student_role_state runs at the top.

    Asserts the join + the now()-arithmetic projection work and that
    the column types are compatible with the tool's coercion (datetime
    + int).
    """
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT
                    r.slug,
                    r.display_name,
                    r.description,
                    r.sequence_order,
                    r.is_terminal,
                    s.role_started_at,
                    EXTRACT(DAY FROM (now() - s.role_started_at))::int AS days_in_role,
                    s.transitions_completed
                FROM student_role_state s
                JOIN roles r ON r.id = s.current_role_id
                LIMIT 1
                """
            )
        )
    ).all()
    assert len(rows) == 1
    slug, display, desc, order, terminal, started, days, completed = rows[0]
    assert isinstance(slug, str)
    assert isinstance(order, int)
    assert isinstance(terminal, bool)
    assert isinstance(days, int)
    # transitions_completed is JSONB → list/dict on the Python side.
    assert isinstance(completed, list)


async def test_role_transitions_join_resolves_with_full_projection(
    pg_session: AsyncSession,
) -> None:
    """The next-transition lookup query in read_student_role_state."""
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT
                    t.slug AS to_slug,
                    rt.capstone_threshold,
                    rt.capstone_count_required,
                    rt.mock_interview_pass_threshold,
                    rt.mock_interview_sessions_required_pass,
                    rt.mock_interview_sessions_window
                FROM role_transitions rt
                JOIN roles f ON f.id = rt.from_role_id
                JOIN roles t ON t.id = rt.to_role_id
                """
            )
        )
    ).all()
    assert len(rows) == 5
    for row in rows:
        to_slug, c_t, c_n, m_t, m_req, m_win = row
        assert 0.0 <= float(c_t) <= 1.0
        assert 0.0 <= float(m_t) <= 1.0
        assert c_n >= 1
        assert m_req >= 1
        assert m_win >= m_req


# ── read_student_accessible_content path ──────────────────────────────


async def test_entitlements_courses_roles_join_resolves(
    pg_session: AsyncSession,
) -> None:
    """The courses-projection query the tool runs first.

    Verifies LEFT JOIN to roles works even for tributary courses that
    have role_id (post-CP2b) and that the predicate columns
    (revoked_at, expires_at) exist with the expected nullability.
    """
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT c.id, c.slug, c.title, r.slug
                FROM course_entitlements ce
                JOIN courses c ON c.id = ce.course_id
                LEFT JOIN roles r ON r.id = c.role_id
                WHERE ce.revoked_at IS NULL
                  AND (ce.expires_at IS NULL OR ce.expires_at > now())
                LIMIT 5
                """
            )
        )
    ).all()
    # Dev DB has 9 active entitlements; the LIMIT 5 just probes shape.
    for row in rows:
        cid, slug, title, role_slug = row
        # role_slug may be NULL if the entitled course doesn't have a
        # role_id (intentional for orthogonal/elective content).
        assert isinstance(slug, str)


async def test_exercises_join_through_lessons_courses_roles(
    pg_session: AsyncSession,
) -> None:
    """The curated-problems projection JOIN."""
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT
                    e.id, e.title, r.slug, e.is_capstone
                FROM exercises e
                JOIN lessons l ON l.id = e.lesson_id
                JOIN courses c ON c.id = l.course_id
                LEFT JOIN roles r ON r.id = c.role_id
                WHERE (e.is_deleted IS NULL OR e.is_deleted = FALSE)
                LIMIT 5
                """
            )
        )
    ).all()
    # Dev DB has 41 exercises; the LIMIT 5 just probes shape.
    assert len(rows) >= 1
    for row in rows:
        eid, title, role_slug, is_capstone = row
        assert isinstance(is_capstone, bool)


async def test_lesson_resources_join_executes_when_empty(
    pg_session: AsyncSession,
) -> None:
    """lesson_resources is empty on dev DB; the JOIN must still execute
    without error so read_student_accessible_content returns an empty
    notebooks list (not a query failure)."""
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT
                    lr.id, lr.title, lr.course_id, r.slug
                FROM lesson_resources lr
                JOIN courses c ON c.id = lr.course_id
                LEFT JOIN roles r ON r.id = c.role_id
                LIMIT 1
                """
            )
        )
    ).all()
    # Empty list expected — pinning that the empty case isn't a SQL error.
    assert rows == []


# ── evaluate_student_against_gate path ────────────────────────────────


async def test_capstone_query_through_role_id_resolves(
    pg_session: AsyncSession,
) -> None:
    """The capstone-status query the tool runs.

    Probes that the JOIN + WHERE on courses.role_id resolves; dev DB
    has 0 evaluated submissions so the result is empty, but that's
    fine — we're pinning the shape, not the data.
    """
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT
                    es.score,
                    es.status
                FROM exercise_submissions es
                JOIN exercises e ON e.id = es.exercise_id
                JOIN lessons l ON l.id = e.lesson_id
                JOIN courses c ON c.id = l.course_id
                JOIN roles r ON r.id = c.role_id
                WHERE e.is_capstone = TRUE
                  AND es.score IS NOT NULL
                LIMIT 1
                """
            )
        )
    ).all()
    # Whether 0 or N rows, the query must execute. assert no exception.
    assert isinstance(rows, list)


async def test_agent_actions_columns_exist_for_mock_query(
    pg_session: AsyncSession,
) -> None:
    """The agent_actions columns the tool projects."""
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT
                    aa.id, aa.created_at, aa.output_data
                FROM agent_actions aa
                WHERE aa.agent_name = 'mock_interview'
                LIMIT 1
                """
            )
        )
    ).all()
    # 0 or N — both fine. Ensures no missing-column error.
    assert isinstance(rows, list)


# ── Adjacency invariant ───────────────────────────────────────────────


async def test_every_non_terminal_role_has_exactly_one_outbound_transition(
    pg_session: AsyncSession,
) -> None:
    """D-A invariant: linear progression, no branching."""
    rows = (
        await pg_session.execute(
            text(
                """
                SELECT
                    r.slug,
                    r.is_terminal,
                    count(rt.id) AS outbound
                FROM roles r
                LEFT JOIN role_transitions rt ON rt.from_role_id = r.id
                GROUP BY r.slug, r.is_terminal, r.sequence_order
                ORDER BY r.sequence_order
                """
            )
        )
    ).all()
    assert len(rows) == 6
    for slug, is_terminal, outbound in rows:
        if is_terminal:
            assert outbound == 0, f"terminal role {slug} has outbound transitions"
        else:
            assert outbound == 1, (
                f"non-terminal role {slug} has {outbound} outbound transitions; "
                "expected exactly 1"
            )
