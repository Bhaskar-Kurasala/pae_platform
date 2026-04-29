"""F11 — refund_offers: admin-reviewed refund proposals for paid_silent + day_14 students.

When a paid student crosses Slip 4 day 14 (paid_silent + days_since_last_session > 14)
the system surfaces a refund-offer card on /admin/students/{id}. Admin reviews the
context, types a short reason, and clicks "Send offer" — that creates one row here
plus a linked outreach_log row (the actual email send). Status flips as the student
responds.

Numbering note: at branch time, `backend/alembic/versions/` on main contains
0048 → 0049 → 0051 (0050 is the historical gap from F0 — student_notes turned out to
already exist from Phase 3's `0014_student_notes`, so F0 just bumped past). We take
0052 chained off 0051. F8 (in-app DM, Tier 2) is targeting an adjacent slot in
parallel against the running docker stack but its migration file isn't yet
committed to git on main, so the canonical merge path here is 0051 → 0052.
If F8 merges first, this file should be renumbered to 0053 with down_revision
flipped to `0052_student_messages` to keep the chain linear.

Revision ID: 0052_refund_offers
Revises: 0051_outreach_log
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0052_refund_offers"
down_revision: str | None = "0051_outreach_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refund_offers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The admin who clicked "Send offer". NULL when the human leaves
        # the platform (we don't lose the audit trail of the refund itself,
        # we just lose the attribution to a deleted account).
        sa.Column(
            "proposed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # 'proposed' — written but email not yet sent (rare race-state).
        # 'sent'     — outreach_log row created + SendGrid (or mocked) call returned.
        # 'accepted' — student replied yes; payments flow handles the actual refund.
        # 'declined' — student replied no, doesn't want a refund (will keep using).
        # 'expired'  — no reply within the response window (default 14 days).
        sa.Column("status", sa.String(32), nullable=False, server_default="'proposed'"),
        # Short admin-typed context shown in the email body and the
        # admin's own audit trail. Not student-visible verbatim — the
        # template builds its own copy; this is for the operator.
        sa.Column("reason", sa.Text(), nullable=True),
        # Foreign key to the outreach_log row representing the actual
        # email send. Lets the admin UI render "sent at <time> · opened
        # at <time>" by joining one table. NULL until send succeeds.
        sa.Column(
            "outreach_log_id",
            UUID(as_uuid=True),
            sa.ForeignKey("outreach_log.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "proposed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Hot read: list_open_for_user filters by user_id + status. Most
    # users have zero refund_offers ever, so a covering composite index
    # keeps this trivial.
    op.create_index(
        "ix_refund_offers_user_status",
        "refund_offers",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_refund_offers_user_status", table_name="refund_offers")
    op.drop_table("refund_offers")
