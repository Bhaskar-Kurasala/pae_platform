"""D18 Phase A CP2 — smoke tests for the playwright_test database.

Verifies the template-clone produced the expected seed state:
  * 6 roles (from migration 0061)
  * 5 role_transitions (from migration 0061)
  * 11 catalog courses with role_id backfill (per CP2 create_template
    + the 0064 backfill SQL re-applied at template build)
  * 0 users (template is intentionally user-empty; per-test fixtures
    own user state)

Pre-condition: docker compose stack running + create_template.py has
been executed at least once (creates playwright_test_template).
The conftest fixture playwright_db_reset clones playwright_test from
the template at session scope before any test runs.

These smoke tests use only db_session (no Playwright `page`); they
exercise the DB infrastructure in isolation. CP6 final smoke
exercises the full stack including frontend.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.asyncio]


_EXPECTED_ROLE_SLUGS = {
    "python_developer",
    "data_analyst",
    "data_scientist",
    "ml_engineer",
    "genai_engineer",
    "senior_genai_engineer",
}


async def test_template_database_has_six_roles(
    db_session: AsyncSession,
) -> None:
    """6 roles seeded by migration 0061."""
    rows = await db_session.execute(sql_text("SELECT slug FROM roles"))
    slugs = {row.slug for row in rows.all()}
    assert len(slugs) == 6
    assert slugs == _EXPECTED_ROLE_SLUGS


async def test_template_database_has_five_role_transitions(
    db_session: AsyncSession,
) -> None:
    """5 role_transitions seeded by migration 0061 — one per non-terminal
    role (the senior_genai_engineer terminal role has no further
    transition).
    """
    count = (
        await db_session.execute(
            sql_text("SELECT COUNT(*) FROM role_transitions")
        )
    ).scalar_one()
    assert count == 5


async def test_template_database_has_eleven_courses_with_role_id_backfill(
    db_session: AsyncSession,
) -> None:
    """CP2 create_template seeds the 11 canonical catalog courses + applies
    the 0064 backfill so every course has a role_id.

    Note vs dev DB: dev has 12 courses (11 catalog + 1 d12-smoke-course
    test artifact with role_id=NULL). The template intentionally
    excludes the test artifact, so courses-total == courses-with-role_id
    == 11. Pattern 23 caught this drift between dev DB shape and
    template-canonical shape during CP2 pre-flight.
    """
    total = (
        await db_session.execute(sql_text("SELECT COUNT(*) FROM courses"))
    ).scalar_one()
    with_role = (
        await db_session.execute(
            sql_text("SELECT COUNT(*) FROM courses WHERE role_id IS NOT NULL")
        )
    ).scalar_one()
    assert total == 11, f"expected 11 catalog courses, got {total}"
    assert with_role == 11, (
        f"expected all 11 courses to have role_id (backfill), got {with_role}"
    )


async def test_template_database_user_state_empty(
    db_session: AsyncSession,
) -> None:
    """Template is intentionally user-empty; per-test fixtures own user
    state. If this fails post-suite, a prior test's fixture didn't
    clean up — but the next suite run resets from template, so the
    next pytest run still starts clean.
    """
    count = (
        await db_session.execute(sql_text("SELECT COUNT(*) FROM users"))
    ).scalar_one()
    assert count == 0, (
        f"template should be user-empty; got {count} users — a prior "
        "test's fixture leaked, OR create_template.py started seeding "
        "users (intentional design change?)."
    )
