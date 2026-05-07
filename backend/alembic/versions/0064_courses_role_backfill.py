"""D15 CP2b — backfill courses.role_id (tier 1 auto + tier 2 founder-decided).

Two-tier strategy from the CP2a audit
(d15-cp2-content-role-mapping-audit.md):

  Tier 1 — slug convention auto-backfill:
    For each role, set role_id on the course whose slug equals the
    role's slug with hyphens (replace _ → -). Five matches expected:
    python-developer → python_developer, data-analyst → data_analyst,
    data-scientist → data_scientist, ml-engineer → ml_engineer,
    genai-engineer → genai_engineer.

  Tier 2 — founder-decided tributary mappings (2026-05-08):
    python-foundations            → python_developer
    intro-ai-engineering          → genai_engineer
    production-rag                → genai_engineer
    llm-evaluation                → senior_genai_engineer
    agent-orchestration-langgraph → senior_genai_engineer
    data-analyst-path             → data_analyst
    d12-smoke-course              → NULL (test fixture, intentionally
                                          unmapped)

    Reasoning preserved at docs/followups/d15-cp2-content-role-mapping
    -audit.md and the conversation thread that led to this commit. The
    senior_genai_engineer mappings give the terminal role two courses of
    progression-content — rubric design + agent orchestration are both
    architecture-level skills per the role identity statement.

Net effect post-migration: every role has at least one course mapped.
Capstones become visible to gate evaluation:
  - python_developer transition gate: 1 capstone (python-foundations)
  - genai_engineer transition gate: 2 capstones (intro-ai-engineering)
  - other transitions: 0 capstones until content is authored

Idempotency: each UPDATE is keyed by course.slug, so re-running the
migration after a downgrade-then-upgrade cycle produces the same final
state. The migration does NOT touch courses whose role_id is already
non-NULL — so a manual admin override (set via DB after a future
re-author) survives a re-run.

Revision ID: 0064_courses_role_backfill
Revises: 0063_courses_role_fk
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064_courses_role_backfill"
down_revision: str | None = "0063_courses_role_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Founder-decided tier 2 mappings (2026-05-08). Hardcoded so the
# migration is self-contained and replayable. Format:
#   course_slug: role_slug | None
TIER_2_MAPPINGS: list[tuple[str, str | None]] = [
    ("python-foundations", "python_developer"),
    ("intro-ai-engineering", "genai_engineer"),
    ("production-rag", "genai_engineer"),
    ("llm-evaluation", "senior_genai_engineer"),
    ("agent-orchestration-langgraph", "senior_genai_engineer"),
    ("data-analyst-path", "data_analyst"),
    # d12-smoke-course intentionally omitted — stays NULL.
]


def upgrade() -> None:
    # ── Tier 1: slug-convention auto-backfill ───────────────────────
    # `replace(course.slug, '-', '_') == role.slug` matches the five
    # role-named courses exactly. Only updates rows where role_id is
    # currently NULL so this stays idempotent across re-runs and never
    # clobbers a manual admin override.
    op.execute(
        sa.text(
            """
            UPDATE courses c
            SET role_id = r.id
            FROM roles r
            WHERE c.role_id IS NULL
              AND replace(c.slug, '-', '_') = r.slug
            """
        )
    )

    # ── Tier 2: founder-decided tributary mappings ──────────────────
    # Per-pair UPDATE with a nested SELECT so the migration is explicit
    # about what's mapped where. Resolves the role slug to id at apply
    # time (works against any DB where the seeds from 0061 have been
    # applied — i.e., any DB at this revision or later).
    for course_slug, role_slug in TIER_2_MAPPINGS:
        op.execute(
            sa.text(
                """
                UPDATE courses
                SET role_id = (SELECT id FROM roles WHERE slug = :role_slug)
                WHERE slug = :course_slug
                  AND role_id IS NULL
                """
            ).bindparams(course_slug=course_slug, role_slug=role_slug)
        )


def downgrade() -> None:
    # Clear role_id on the rows this migration set. The schema column
    # itself is preserved (0063 owns its lifecycle); this just rolls
    # back the data fill so a partial downgrade leaves the table
    # available with empty role tags.
    op.execute(sa.text("UPDATE courses SET role_id = NULL"))
