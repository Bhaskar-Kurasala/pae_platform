"""D18 Phase A CP2 — create the playwright_test_template database.

Source of truth for the Playwright test database template. Idempotent;
re-runnable. Run once before the suite (CI does this in the build
step; local developers run manually after schema changes).

What lands in the template:
  * Full alembic schema (alembic upgrade head)
  * 6 roles + 5 role_transitions (seeded by migration 0061)
  * 11 catalog courses with role_id backfill (per D15 CP2b mappings;
    excludes the `d12-smoke-course` dev-DB test artifact)
  * No users, no enrollments, no submissions, no agent_actions, no
    outreach rows. Per-test fixtures own that surface (see
    backend/tests/fixtures/role_state_fixtures.py + journey_fixtures.py
    landing in CP4).

Why the template is user-empty:
  Playwright fixtures need exact control over user state per test
  (a stalled student vs a momentum student vs a fresh signup all
  start from the same template + fixture-specific seed). Including
  default users in the template would force every test to either
  use those users (coupling) or clean them up first (slower).

Why courses are seeded but users aren't:
  Courses are content (instructor-authored, stable across test runs).
  Users are state (per-scenario, per-test). The template captures
  the stable surface; fixtures own the per-scenario surface.

Postgres TEMPLATE feature (verified at CP2 pre-flight):
  Postgres 16.x supports `CREATE DATABASE foo TEMPLATE bar`.
  Cloning a fully-seeded template runs in ~1-2s vs ~30-60s for
  re-running migrations + re-seeding from scratch. That's the speed
  budget Playwright suite startup needs.

Usage:
  # From the host (preferred — uses docker compose port mapping):
  python backend/tests/playwright/db/create_template.py

  # Or from inside the backend container:
  docker compose exec backend uv run python \\
    /app/tests/playwright/db/create_template.py

  # Override the admin-DSN target (default points at the docker-compose
  # `db` service; CI may need a different host):
  PLAYWRIGHT_ADMIN_DSN=postgresql://postgres:postgres@db:5432/postgres \\
    python backend/tests/playwright/db/create_template.py

The script connects to the maintenance DB (`postgres`) for DROP/CREATE
DATABASE, then to `playwright_test_template` for migrations + seed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import asyncpg

# CP1 conftest documents the canonical layout; this script lives at
# backend/tests/playwright/db/. To run alembic against the template,
# we set DATABASE_URL and shell out to `alembic upgrade head`.

TEMPLATE_DB_NAME = "playwright_test_template"
DEFAULT_ADMIN_DSN = (
    "postgresql://postgres:postgres@db:5432/postgres"
)


def _admin_dsn() -> str:
    """Return the connection string for the maintenance database.

    Defaults to the docker-compose `db` service (works when this script
    runs inside the backend container or against a `db:5432` mapping).
    Override via PLAYWRIGHT_ADMIN_DSN for host-run scenarios where the
    Postgres host is something other than `db` (e.g. `localhost:5433`).
    """
    return os.environ.get("PLAYWRIGHT_ADMIN_DSN", DEFAULT_ADMIN_DSN)


def _template_dsn() -> str:
    """Return the connection string for the template database itself."""
    base = _admin_dsn()
    # Replace the trailing /postgres database name with /playwright_test_template
    if base.endswith("/postgres"):
        return base[: -len("postgres")] + TEMPLATE_DB_NAME
    raise ValueError(
        f"PLAYWRIGHT_ADMIN_DSN must end in /postgres; got {base!r}"
    )


# ── 11 canonical catalog courses (slug + title only; role_id filled
# by the backfill SQL below, mirroring migration 0064's mappings).
#
# Excludes the `d12-smoke-course` test artifact present on the dev DB
# but not part of the canonical catalog. Per CP2 pre-flight Pattern 23
# verification: dev DB has 12 courses (11 with role_id + 1 without);
# the `without` is dev-only test pollution. Template seeds the 11
# canonical courses; smoke test asserts both `total == 11` and
# `with-role_id == 11`.
_CATALOG_COURSES: tuple[tuple[str, str], ...] = (
    ("python-developer", "Python Developer"),
    ("python-foundations", "Python Foundations"),
    ("data-analyst", "Data Analyst"),
    ("data-analyst-path", "Data Analyst Path"),
    ("data-scientist", "Data Scientist"),
    ("ml-engineer", "ML Engineer"),
    ("genai-engineer", "GenAI Engineer"),
    ("intro-ai-engineering", "Intro to AI Engineering"),
    ("production-rag", "Production RAG"),
    ("llm-evaluation", "LLM Evaluation"),
    ("agent-orchestration-langgraph", "Agent Orchestration with LangGraph"),
)


async def _drop_database_if_exists(conn: asyncpg.Connection, name: str) -> None:
    # asyncpg requires CREATE/DROP DATABASE to be top-level (no
    # transaction wrapper); execute directly. The IF EXISTS clause
    # makes this idempotent.
    await conn.execute(f"DROP DATABASE IF EXISTS {name}")


async def _create_database(conn: asyncpg.Connection, name: str) -> None:
    await conn.execute(f"CREATE DATABASE {name}")


async def _seed_courses(conn: asyncpg.Connection) -> None:
    """Insert the 11 catalog courses into the template database.

    Uses ON CONFLICT (slug) DO NOTHING for idempotency — running the
    seed twice produces the same final row set. Subsequent runs only
    matter if create_template is invoked against an already-populated
    template (the canonical use re-creates from scratch, so this is
    defense-in-depth).
    """
    for slug, title in _CATALOG_COURSES:
        await conn.execute(
            """
            INSERT INTO courses
              (id, slug, title, description, price_cents, is_published,
               metadata, created_at, updated_at)
            VALUES
              (gen_random_uuid(), $1, $2, $3, 0, TRUE,
               '{}'::json, now(), now())
            ON CONFLICT (slug) DO NOTHING
            """,
            slug,
            title,
            f"Catalog course: {title}.",
        )


async def _backfill_courses_role_id(conn: asyncpg.Connection) -> None:
    """Apply the same role_id backfill migration 0064 runs.

    Migration 0064 backfills against rows that exist AT MIGRATION TIME.
    The template database runs migrations BEFORE courses are seeded
    (the schema must exist before INSERT can succeed), so 0064's
    backfill is a no-op against the empty template. This function
    re-applies the same SQL after the seed lands.

    Mirrors 0064 exactly: tier 1 (slug-convention auto) + tier 2
    (founder-decided tributary mappings). Idempotent + slug-keyed
    same as the migration.
    """
    # Tier 1 — slug-convention: replace `-` with `_` in course slug,
    # match against role slug.
    await conn.execute(
        """
        UPDATE courses c
        SET role_id = r.id
        FROM roles r
        WHERE c.role_id IS NULL
          AND replace(c.slug, '-', '_') = r.slug
        """
    )

    # Tier 2 — founder-decided mappings. Mirrors TIER_2_MAPPINGS in
    # migration 0064. Keep in sync with that migration.
    tier_2 = (
        ("python-foundations", "python_developer"),
        ("intro-ai-engineering", "genai_engineer"),
        ("production-rag", "genai_engineer"),
        ("llm-evaluation", "senior_genai_engineer"),
        ("agent-orchestration-langgraph", "senior_genai_engineer"),
        ("data-analyst-path", "data_analyst"),
    )
    for course_slug, role_slug in tier_2:
        await conn.execute(
            """
            UPDATE courses
            SET role_id = (SELECT id FROM roles WHERE slug = $1)
            WHERE slug = $2
              AND role_id IS NULL
            """,
            role_slug,
            course_slug,
        )


async def _run_alembic_against_template() -> None:
    """Shell out to alembic upgrade head against the template DSN.

    Pre-flight Pattern 23 finding: alembic/env.py:23 reads DATABASE_URL
    env var FIRST (before falling back to settings.database_url built
    from POSTGRES_*). The backend container's .env sets DATABASE_URL
    pointing at the dev `platform` DB, so overriding POSTGRES_DB alone
    has no effect — DATABASE_URL wins. Override DATABASE_URL directly
    to point alembic at the template DB. Discovered when an early
    create_template.py run reported alembic success but the template
    was still empty (alembic was actually upgrading the dev DB to its
    already-current head).
    """
    # asyncpg-shape DSN → SQLAlchemy/alembic shape. _template_dsn()
    # returns "postgresql://...", alembic env.py rewrites
    # "postgresql://" → "postgresql+asyncpg://" itself, so passing the
    # asyncpg-flavored URL directly also works; safer to be explicit.
    template_url = _template_dsn().replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
    import subprocess

    env = os.environ.copy()
    env["DATABASE_URL"] = template_url

    proc = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env=env,
        cwd="/app" if os.path.exists("/app/alembic.ini") else "backend",
    )
    if proc.returncode != 0:
        print("alembic stdout:\n" + proc.stdout, file=sys.stderr)
        print("alembic stderr:\n" + proc.stderr, file=sys.stderr)
        raise RuntimeError(
            f"alembic upgrade head failed against {TEMPLATE_DB_NAME} "
            f"(exit {proc.returncode})"
        )


async def main() -> int:
    started = time.monotonic()

    print(f"[create_template] target: {_template_dsn()}", file=sys.stderr)

    # ── Step 1: drop + create the template database ────────────────
    print("[create_template] step 1/3: drop + create template database",
          file=sys.stderr)
    admin_conn = await asyncpg.connect(_admin_dsn())
    try:
        await _drop_database_if_exists(admin_conn, TEMPLATE_DB_NAME)
        await _create_database(admin_conn, TEMPLATE_DB_NAME)
    finally:
        await admin_conn.close()

    # ── Step 2: alembic upgrade head against the template ──────────
    # This seeds 6 roles + 5 role_transitions via migration 0061; adds
    # the failure_class enum + check constraint via 0066; etc.
    step_2_started = time.monotonic()
    print("[create_template] step 2/3: alembic upgrade head", file=sys.stderr)
    await _run_alembic_against_template()
    step_2_elapsed = time.monotonic() - step_2_started
    print(
        f"[create_template]            done in {step_2_elapsed:.2f}s",
        file=sys.stderr,
    )

    # ── Step 3: seed 11 catalog courses + backfill role_id ─────────
    step_3_started = time.monotonic()
    print("[create_template] step 3/3: seed catalog courses + backfill role_id",
          file=sys.stderr)
    template_conn = await asyncpg.connect(_template_dsn())
    try:
        await _seed_courses(template_conn)
        await _backfill_courses_role_id(template_conn)

        # Sanity check: surface what landed before the script exits.
        roles = await template_conn.fetchval("SELECT COUNT(*) FROM roles")
        transitions = await template_conn.fetchval(
            "SELECT COUNT(*) FROM role_transitions"
        )
        courses = await template_conn.fetchval("SELECT COUNT(*) FROM courses")
        courses_with_role = await template_conn.fetchval(
            "SELECT COUNT(*) FROM courses WHERE role_id IS NOT NULL"
        )
        users = await template_conn.fetchval("SELECT COUNT(*) FROM users")
    finally:
        await template_conn.close()
    step_3_elapsed = time.monotonic() - step_3_started
    print(
        f"[create_template]            done in {step_3_elapsed:.2f}s",
        file=sys.stderr,
    )

    elapsed = time.monotonic() - started
    print(
        f"[create_template] template ready in {elapsed:.2f}s "
        f"(roles={roles}, role_transitions={transitions}, "
        f"courses={courses}, courses_with_role_id={courses_with_role}, "
        f"users={users})",
        file=sys.stderr,
    )

    if (
        roles != 6
        or transitions != 5
        or courses != 11
        or courses_with_role != 11
        or users != 0
    ):
        print(
            "[create_template] FATAL: seed counts don't match expected "
            "(6/5/11/11/0). Surface the discrepancy before continuing.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
