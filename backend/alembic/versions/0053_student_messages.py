"""F8 — student_messages: in-app direct messaging between admin and student.

Two-party conversation thread: admin sends nudges + check-ins ("hey I
noticed you've been stuck on Lab B — try this hint"), student replies
in-app. The student's reply flips the originating outreach_log's
replied_at, closing the loop on F3's audit trail.

Revision ID: 0053_student_messages
Revises: 0052_refund_offers

Numbered 0053 because F11 (refund_offers) merged 0052 in parallel.
Both branches originally chained off 0051; F8 renumbered to land on
top of F11 once F11's merge landed first. Same schema; only the
revision metadata moved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0053_student_messages"
down_revision: str | None = "0052_refund_offers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "student_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        # thread_id groups messages of the same conversation. We use a
        # client-generated UUID rather than a conversation table because
        # threads are between EXACTLY two parties (admin + one student)
        # — a separate threads table is unnecessary indirection. The
        # thread_id is created the first time admin starts a thread,
        # then reused for every reply.
        sa.Column("thread_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "student_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # 'admin' | 'student' — denormalized so we can render thread
        # bubbles without joining to the users table for sender role.
        sa.Column("sender_role", sa.String(16), nullable=False),
        # The actual user who wrote the message — admin user_id or the
        # student themselves. ON DELETE SET NULL because if an admin
        # account is later deactivated, the message content survives
        # (we want "someone wrote this" preserved for audit).
        sa.Column(
            "sender_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # 5000-char cap is enforced at the API validation layer; the
        # column is plain TEXT so a bug there can't truncate.
        sa.Column("body", sa.Text(), nullable=False),
        # Read tracking. NULL = unread, timestamp = when the recipient
        # opened it. The unread-count poller reads this.
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        # Soft delete via deleted_at — keeps an audit trail even after
        # admin "removes" a message. The list endpoints filter by
        # deleted_at IS NULL.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # The student-side inbox query: "all my threads ordered by
    # most-recent message first." Index covers the WHERE + ORDER BY.
    op.create_index(
        "ix_student_messages_student",
        "student_messages",
        ["student_id", sa.text("created_at DESC")],
    )

    # The thread-detail query: "all messages in this thread, oldest
    # first." (student_id, thread_id, created_at) covers the auth
    # filter (student_id ensures one student can't load another's
    # thread by guessing a UUID) plus the ORDER BY.
    op.create_index(
        "ix_student_messages_thread",
        "student_messages",
        ["thread_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_student_messages_thread", table_name="student_messages")
    op.drop_index("ix_student_messages_student", table_name="student_messages")
    op.drop_table("student_messages")
