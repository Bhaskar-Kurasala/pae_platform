"""conversations pinned_at (P1-8)

Revision ID: 0031
Revises: 0030
Create Date: 2026-04-19 22:00:00.000000

Adds `conversations.pinned_at TIMESTAMPTZ NULL` so the sidebar can surface
pinned threads above the rest. A nullable timestamp (rather than a boolean
+ separate `pinned_at`) keeps the ordering cheap: `ORDER BY pinned_at DESC
NULLS LAST, updated_at DESC` gives pinned-first + stable ordering of the
non-pinned tail without a second SQL pass.

A plain index on `pinned_at` keeps the sidebar's pinned-first ORDER BY
plan-stable even as the per-user row count grows. No partial index so the
same DDL runs on SQLite (tests) and Postgres (prod).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "pinned_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_conversations_pinned_at",
        "conversations",
        ["pinned_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_pinned_at", table_name="conversations")
    op.drop_column("conversations", "pinned_at")
