"""F0/F3 — outreach_log: every system or admin outreach to a student.

Created as F0 plumbing so F3 service + F5 email + F9 nightly automation
all read/write through this single audit table. Building the audit
table BEFORE the senders means we never have to retrofit "who did we
already email this week" into 50 ad-hoc call sites.

Single source of truth for: did we contact this user, when, on which
channel, with which template, and did they engage? Used by:
  - F3 OutreachService.was_sent_recently — throttle defense
  - F4 admin console (per-student timeline shows recent outreach)
  - F5 email service (writes a row on every send)
  - F9 nightly automation (reads to skip recently-contacted users)

Revision ID: 0051_outreach_log
Revises: 0049_student_risk_signals
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0051_outreach_log"
down_revision: str | None = "0049_student_risk_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outreach_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # 'email' | 'whatsapp' | 'sms' | 'in_app' | 'phone'.
        # Stored as text so adding 'slack' or 'discord' later doesn't
        # need an alter-enum. Validated at the service layer.
        sa.Column("channel", sa.String(32), nullable=False),
        # Maps to a file in app/templates/email/{template_key}.html or
        # equivalent for other channels. NULL when admin sent a one-off
        # ad-hoc message (e.g. a bespoke email through the admin UI).
        sa.Column("template_key", sa.String(128), nullable=True),
        # Denormalized from F1 student_risk_signals at send time so
        # later analytics ("what did we send to capstone-stalled
        # students last month?") doesn't need a 4-table join.
        sa.Column("slip_type", sa.String(64), nullable=True),
        # 'system_nightly' | 'admin_manual' — drives the analytics for
        # "what fraction of outreach is automated vs. handcrafted".
        sa.Column("triggered_by", sa.String(32), nullable=False),
        sa.Column(
            "triggered_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        # First 200 chars of the body for the admin audit trail. Don't
        # store the full message — that's PII bloat. The template key
        # plus the variables can re-derive the body if absolutely needed.
        sa.Column("body_preview", sa.Text(), nullable=True),
        # SendGrid message-id, Twilio sid, etc. Required for matching
        # delivery webhooks back to the originating row.
        sa.Column("external_id", sa.String(255), nullable=True),
        # 'pending' | 'sent' | 'delivered' | 'bounced' | 'failed' | 'mocked'.
        # 'mocked' = no-DSN dev mode where F5 logs but doesn't actually
        # call SendGrid — preserves the audit trail for local QA.
        sa.Column("status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("error", sa.Text(), nullable=True),
    )

    # The throttle check (F3 was_sent_recently) is the hot query:
    #   SELECT 1 FROM outreach_log
    #     WHERE user_id = $1 AND template_key = $2 AND sent_at > $3
    #     LIMIT 1
    # Index covers all three predicates.
    op.create_index(
        "ix_outreach_log_throttle",
        "outreach_log",
        ["user_id", "template_key", sa.text("sent_at DESC")],
    )

    # The F5 webhook handler looks up rows by external_id when a
    # delivery/open event arrives. external_id is unique per row but
    # nullable (some rows have no external — failed sends, mocked).
    op.create_index(
        "ix_outreach_log_external_id",
        "outreach_log",
        ["external_id"],
        unique=False,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outreach_log_external_id", table_name="outreach_log")
    op.drop_index("ix_outreach_log_throttle", table_name="outreach_log")
    op.drop_table("outreach_log")
