"""chat messages soft delete (P1-1)

Revision ID: 0030
Revises: 0029
Create Date: 2026-04-19 20:00:00.000000

Adds `deleted_at` to `chat_messages` for soft-delete semantics. Used by P1-1
(edit last user message) and future branching/regenerate flows so downstream
messages stay in the DB for analytics while being hidden from the chat UI.

`deleted_at` is nullable + timezone-aware. Repository queries filter out
rows with `deleted_at IS NOT NULL` by default; an explicit
`include_deleted=True` flag is required to surface them (used by admin
rollup paths if we ever need it).

A partial index on `(conversation_id, created_at)` for the *active* rows
keeps the default list query fast even as soft-deleted rows pile up.
SQLite (used in tests) doesn't support partial indexes without `WHERE`
support on older versions — the index is skipped there and the planner
falls back to the existing composite index from migration 0028.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Plain (non-partial) index so both Postgres and SQLite can use it. The
    # composite `(conversation_id, created_at)` from migration 0028 already
    # backs the ordered fetch path; this single-column index speeds
    # filtering `deleted_at IS NULL` when pagination widens.
    op.create_index(
        "ix_chat_messages_deleted_at",
        "chat_messages",
        ["deleted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_deleted_at", table_name="chat_messages")
    op.drop_column("chat_messages", "deleted_at")
