"""chat message feedback (P1-5)

Revision ID: 0029
Revises: 0028
Create Date: 2026-04-19 19:00:00.000000

Adds `chat_message_feedback` — thumbs up/down + reason chips + freeform
comment for each assistant reply. One row per (message_id, user_id). A new
rating from the same user on the same message replaces the existing row
(upsert semantics — enforced by the application layer).

`rating` is stored as `String(8)` with a CHECK constraint rather than a
Postgres enum. This matches the prevailing style on `chat_messages.role`
(see migration 0028) and lets us add rating values later without needing an
ALTER TYPE migration.

`reasons` is plain `JSON` (not ARRAY / JSONB) so the same schema renders on
SQLite in tests and Postgres in prod. Typical payload is a short list of
enum-like strings; we don't query into it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_message_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.String(length=8), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "rating IN ('up', 'down')",
            name="ck_chat_message_feedback_rating",
        ),
        sa.UniqueConstraint(
            "message_id", "user_id", name="uq_chat_message_feedback_message_user"
        ),
    )
    op.create_index(
        "ix_chat_message_feedback_message_id",
        "chat_message_feedback",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_message_feedback_user_id",
        "chat_message_feedback",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_message_feedback_user_id", table_name="chat_message_feedback"
    )
    op.drop_index(
        "ix_chat_message_feedback_message_id", table_name="chat_message_feedback"
    )
    op.drop_table("chat_message_feedback")
