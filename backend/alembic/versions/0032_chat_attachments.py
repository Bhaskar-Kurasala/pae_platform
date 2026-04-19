"""chat attachments (P1-6)

Revision ID: 0032
Revises: 0031
Create Date: 2026-04-19 21:00:00.000000

Adds `chat_attachments` — one row per uploaded file/image that the student can
attach to a chat turn. Rows are created pending (`message_id IS NULL`) on POST
`/api/v1/chat/attachments`, then bound to a specific user message on the next
`/api/v1/agents/stream` call by the service layer.

`storage_key` is the opaque reference the `AttachmentStorage` backend resolves
(e.g. for the local-fs impl this is a relative path under
`settings.attachments_dir`). In production we'll swap the backend for S3 and
`storage_key` becomes the S3 object key without a schema change.

`mime_type` is stored verbatim but the service layer restricts the set on
upload (PNG, JPEG, .py/.md/.txt/.ipynb). `size_bytes` is capped at the service
layer (10 MB) and persisted for size-display + quota tracking later.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_chat_attachments_message_id",
        "chat_attachments",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_attachments_user_id",
        "chat_attachments",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_attachments_user_id", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_message_id", table_name="chat_attachments")
    op.drop_table("chat_attachments")
