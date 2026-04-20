"""notebook_entries table

Revision ID: 0034_notebook_entries
Revises: 0033
Create Date: 2026-04-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0034_notebook_entries"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notebook_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_id", sa.String, nullable=False),
        sa.Column("conversation_id", sa.String, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column(
            "tags",
            sa.ARRAY(sa.String),
            nullable=True,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_notebook_entries_user_id", "notebook_entries", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notebook_entries_user_id", table_name="notebook_entries")
    op.drop_table("notebook_entries")
