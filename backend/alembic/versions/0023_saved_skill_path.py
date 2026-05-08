"""saved_skill_paths table (P3 3B-#24 path saving)

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-18 21:00:00.000000

Creates a dedicated table for student-saved skill paths. The
skill_ids_json column stays sa.Text so it works with both SQLite
(unit tests) and PostgreSQL (production).

D18 Phase A CP2 (2026-05-08) historical-drift fix (Pattern 22):
  Original migration declared `id` and `user_id` as sa.String(36) —
  fine on SQLite, but FAILS against fresh Postgres because users.id
  is UUID and the FK can't be implemented with mismatched types
  (DatatypeMismatchError: "user_id" varchar vs "users.id" uuid).
  The dev DB happened to have UUID types here (likely created via
  a non-canonical path that's been smoothed away in the dev migration
  history), so the broken migration never surfaced — until D18 Phase A
  CP2 tried to rebuild the schema from scratch on a fresh template DB.

  Forward-only fix: declare both `id` and `user_id` as UUID(as_uuid=True)
  to match the SavedSkillPath model (UUIDMixin gives id; user_id has
  explicit UUID type). This produces the same shape the dev DB has,
  so no data migration needed; just aligns the migration with reality.

  Pattern 22 reinforcement: the migration chain rebuildability is now
  load-bearing for D18 testing infrastructure, not just historical
  hygiene. Going forward every new migration should be tested against
  a fresh DB before merge — see docs/followups/migration-chain-fresh-
  db-rebuildability.md (registered at this commit).

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_skill_paths",
        # D18 Phase A CP2 historical-drift fix: UUID, not String(36).
        # See module docstring for the rationale.
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("skill_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_saved_skill_paths_user_id"),
    )
    op.create_index("ix_saved_skill_paths_user_id", "saved_skill_paths", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_saved_skill_paths_user_id", table_name="saved_skill_paths")
    op.drop_table("saved_skill_paths")
