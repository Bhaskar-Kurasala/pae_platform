"""admin console v1 — analytics tables for /admin/console

Adds 8 tables that back the CareerForge_admin_v1 console:
  - admin_console_profiles      (student track/stage/risk extensions)
  - admin_console_engagement    (14-day rollups per student)
  - admin_console_funnel_snapshots
  - admin_console_pulse_metrics
  - admin_console_feature_usage
  - admin_console_events        (live event feed)
  - admin_console_calls         (scheduled calls)
  - admin_console_risk_reasons  (top-card narratives)

Revision ID: 0039_admin_console_v1
Revises: 0038_mock_interview_v3
Create Date: 2026-04-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0039_admin_console_v1"
down_revision: str | None = "0038_mock_interview_v3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── admin_console_profiles ──────────────────────────────────────────
    op.create_table(
        "admin_console_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("track", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("progress_pct", sa.Integer, nullable=False, server_default="0"),
        sa.Column("streak_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_seen_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("risk_score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("paid", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("joined_label", sa.String(32), nullable=False),
        sa.Column("city", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_admin_console_profiles_risk",
        "admin_console_profiles",
        ["risk_score"],
    )

    # ── admin_console_engagement ────────────────────────────────────────
    op.create_table(
        "admin_console_engagement",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("sessions_14d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("flashcards_14d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("agent_questions_14d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reviews_14d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("notes_14d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("labs_14d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("capstones_14d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("purchases_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── admin_console_funnel_snapshots ──────────────────────────────────
    op.create_table(
        "admin_console_funnel_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("snapshot_date", sa.Date, nullable=False, unique=True),
        sa.Column("signups", sa.Integer, nullable=False, server_default="0"),
        sa.Column("onboarded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("first_lesson", sa.Integer, nullable=False, server_default="0"),
        sa.Column("paid", sa.Integer, nullable=False, server_default="0"),
        sa.Column("capstone", sa.Integer, nullable=False, server_default="0"),
        sa.Column("promoted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("hired", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── admin_console_pulse_metrics ─────────────────────────────────────
    op.create_table(
        "admin_console_pulse_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric_key", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("display_value", sa.String(32), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False, server_default=""),
        sa.Column("delta_pct", sa.Integer, nullable=False, server_default="0"),
        sa.Column("delta_text", sa.String(64), nullable=False, server_default=""),
        sa.Column("color_hex", sa.String(16), nullable=False, server_default="#5fa37f"),
        sa.Column("invert_delta", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("spark", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── admin_console_feature_usage ─────────────────────────────────────
    op.create_table(
        "admin_console_feature_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feature_key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("count_label", sa.String(32), nullable=False),
        sa.Column("sub_label", sa.String(64), nullable=False),
        sa.Column("is_cold", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("bars", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── admin_console_events ────────────────────────────────────────────
    op.create_table(
        "admin_console_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),  # signup|capstone|promo|purchase|review
        sa.Column("body_html", sa.Text, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_admin_console_events_occurred_at",
        "admin_console_events",
        ["occurred_at"],
    )

    # ── admin_console_calls ─────────────────────────────────────────────
    op.create_table(
        "admin_console_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("display_time", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_admin_console_calls_scheduled_for",
        "admin_console_calls",
        ["scheduled_for"],
    )

    # ── admin_console_risk_reasons ──────────────────────────────────────
    op.create_table(
        "admin_console_risk_reasons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("admin_console_risk_reasons")
    op.drop_index("ix_admin_console_calls_scheduled_for", table_name="admin_console_calls")
    op.drop_table("admin_console_calls")
    op.drop_index(
        "ix_admin_console_events_occurred_at", table_name="admin_console_events"
    )
    op.drop_table("admin_console_events")
    op.drop_table("admin_console_feature_usage")
    op.drop_table("admin_console_pulse_metrics")
    op.drop_table("admin_console_funnel_snapshots")
    op.drop_table("admin_console_engagement")
    op.drop_index(
        "ix_admin_console_profiles_risk", table_name="admin_console_profiles"
    )
    op.drop_table("admin_console_profiles")
