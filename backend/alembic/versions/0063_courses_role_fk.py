"""D15 CP2b — courses.role_id foreign key + partial index.

Adds the explicit role tag to courses that the CP2 audit
(d15-cp2-content-role-mapping-audit.md) identified as missing. Without
this column, role↔content mapping had to rely on slug convention alone,
which left 7 of 12 courses (including the only courses with capstones)
invisible to runtime content discovery.

The column is intentionally nullable: courses orthogonal to the linear
role spine (test fixtures, electives) may legitimately have no role.
The partial index `WHERE role_id IS NOT NULL` keeps the hot-path query
("which courses are tagged for role X?") cheap without paying for the
NULL rows.

Backfill ships in a separate migration (0064) per Pattern 3 — the
schema change is reviewable as one unit, the founder-decided tributary
mappings as another. Rollback discipline stays clean: revert 0064 to
clear all role_id values, revert 0063 to drop the column.

Revision ID: 0063_courses_role_fk
Revises: 0062_role_progression_backfill
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0063_courses_role_fk"
down_revision: str | None = "0062_role_progression_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column(
            "role_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "roles.id",
                ondelete="SET NULL",
                name="fk_courses_role_id",
            ),
            nullable=True,
            comment=(
                "Optional FK to roles. NULL = orthogonal to the linear "
                "role progression (electives, fixtures, future content). "
                "ON DELETE SET NULL: a role-row removal de-tags the "
                "course rather than cascading content destruction."
            ),
        ),
    )
    # Partial index: only non-NULL role_ids matter for the hot-path
    # "what content is tagged for role X" query. Skipping NULL rows
    # keeps the index lean — 7 of 12 dev rows would otherwise be NULL
    # and pay storage for nothing.
    op.create_index(
        "idx_courses_role_id",
        "courses",
        ["role_id"],
        postgresql_where=sa.text("role_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_courses_role_id", table_name="courses")
    op.drop_constraint("fk_courses_role_id", "courses", type_="foreignkey")
    op.drop_column("courses", "role_id")
