"""feedback table (3B #177)

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-18 19:00:00.000000

Adds a `feedback` table for the floating feedback widget.
Submissions can be anonymous (user_id nullable).

D18 Phase A CP2 (2026-05-08) historical-drift fix (Pattern 22, sibling
to 0023): the original migration both passed `index=True` on the
user_id Column AND issued an explicit `op.create_index("ix_feedback_user_id"
...)` on the same column. SQLAlchemy auto-names the column-level index
`ix_<table>_<column>` so the two collide on Postgres
(`DuplicateTableError: relation "ix_feedback_user_id" already exists`).
SQLite tolerates the duplicate silently which is why this migration
shipped through unit tests but never ran on a fresh Postgres DB; dev
DB has a single index because it was advanced via a non-canonical
path that smoothed the duplicate.

Forward-only fix: drop `index=True` from the Column declaration and
keep the explicit `op.create_index` (the more visible/searchable
convention; the index name becomes load-bearing for downgrade()). No
data migration; produces the same end-state shape the dev DB has.

Surfaced during D18 Phase A CP2 chain survey (Option C: K-discovery
pass after the 0023 fix). See docs/followups/migration-chain-fresh-
db-rebuildability.md for the full chain-rebuildability discipline.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        # D18 Phase A CP2 fix: dropped `index=True` here because the
        # explicit op.create_index below already creates the same
        # named index. See module docstring.
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("route", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("sentiment", sa.String(20), nullable=True),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_user_id", table_name="feedback")
    op.drop_table("feedback")
