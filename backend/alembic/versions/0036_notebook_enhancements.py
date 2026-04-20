"""notebook_entries enhancements — user_note, source_type, topic, last_reviewed_at

Revision ID: 0036_notebook_enhancements
Revises: 0035_career_tables_v2
Create Date: 2026-04-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0036_notebook_enhancements"
down_revision: str | None = "0035_career_tables_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notebook_entries",
        sa.Column("user_note", sa.Text, nullable=True),
    )
    op.add_column(
        "notebook_entries",
        sa.Column("source_type", sa.String(50), nullable=True, server_default="chat"),
    )
    op.add_column(
        "notebook_entries",
        sa.Column("topic", sa.String(200), nullable=True),
    )
    op.add_column(
        "notebook_entries",
        sa.Column(
            "last_reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("notebook_entries", "last_reviewed_at")
    op.drop_column("notebook_entries", "topic")
    op.drop_column("notebook_entries", "source_type")
    op.drop_column("notebook_entries", "user_note")
