"""saved_skill_paths table (P3 3B-#24 path saving)

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-18 21:00:00.000000

Creates a dedicated table for student-saved skill paths.  Uses sa.Text to
store a JSON-encoded list of UUIDs — compatible with both SQLite (tests) and
PostgreSQL (production).

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_skill_paths",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
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
