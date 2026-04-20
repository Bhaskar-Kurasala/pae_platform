"""chat_messages metadata (P2-5)

Revision ID: 0033
Revises: 0032
Create Date: 2026-04-20 10:00:00.000000

Adds hover-visible performance + provenance metadata to `chat_messages`:

  - `first_token_ms`    : ms from request arrival to first streamed token
  - `total_duration_ms` : ms from request arrival to `done:true`
  - `input_tokens`      : prompt token count (langchain `usage_metadata`)
  - `output_tokens`     : completion token count
  - `model`             : concrete model id chosen by the routed agent

Every column is nullable so historical rows and failure paths (stream
error mid-flight, usage_metadata missing) surface as "—" in the UI
rather than breaking the render.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("first_token_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column("total_duration_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column("input_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column("output_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column("model", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "model")
    op.drop_column("chat_messages", "output_tokens")
    op.drop_column("chat_messages", "input_tokens")
    op.drop_column("chat_messages", "total_duration_ms")
    op.drop_column("chat_messages", "first_token_ms")
