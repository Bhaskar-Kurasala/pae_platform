"""mock interview v3 — extend interview_sessions + new mock_* tables

Revision ID: 0038_mock_interview_v3
Revises: 0037_tailored_resume
Create Date: 2026-04-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0038_mock_interview_v3"
down_revision: str | None = "0037_tailored_resume"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Extend interview_sessions ────────────────────────────────────────
    op.add_column(
        "interview_sessions",
        sa.Column("target_role", sa.String(255), nullable=True),
    )
    op.add_column(
        "interview_sessions",
        sa.Column("level", sa.String(20), nullable=True),  # junior|mid|senior
    )
    op.add_column(
        "interview_sessions",
        sa.Column("jd_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "interview_sessions",
        sa.Column("voice_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "interview_sessions",
        sa.Column("total_cost_inr", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.add_column(
        "interview_sessions",
        sa.Column("share_token", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_interview_sessions_share_token",
        "interview_sessions",
        ["share_token"],
        unique=True,
    )

    # ── mock_questions ──────────────────────────────────────────────────
    op.create_table(
        "mock_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(40), nullable=False),
        sa.Column("difficulty", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("source", sa.String(40), nullable=False, server_default="generated"),
        sa.Column(
            "parent_question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mock_questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rubric", sa.JSON(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── mock_answers ────────────────────────────────────────────────────
    op.create_table(
        "mock_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mock_questions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("audio_ref", sa.String(512), nullable=True),
        sa.Column("evaluation", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("filler_word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("time_to_first_word_ms", sa.Integer(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── mock_session_reports ────────────────────────────────────────────
    op.create_table(
        "mock_session_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("rubric_summary", sa.JSON(), nullable=True),
        sa.Column("patterns", sa.JSON(), nullable=True),
        sa.Column("strengths", sa.JSON(), nullable=True),
        sa.Column("weaknesses", sa.JSON(), nullable=True),
        sa.Column("next_action", sa.JSON(), nullable=True),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("verdict", sa.String(40), nullable=True),
        sa.Column("analyst_confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── mock_weakness_ledger ────────────────────────────────────────────
    op.create_table(
        "mock_weakness_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("concept", sa.String(255), nullable=False),
        sa.Column("severity", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("evidence_session_ids", sa.JSON(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("addressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_mock_weakness_ledger_user_concept",
        "mock_weakness_ledger",
        ["user_id", "concept"],
        unique=True,
    )

    # ── mock_cost_log ───────────────────────────────────────────────────
    op.create_table(
        "mock_cost_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("sub_agent", sa.String(40), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("mock_cost_log")
    op.drop_index(
        "ix_mock_weakness_ledger_user_concept", table_name="mock_weakness_ledger"
    )
    op.drop_table("mock_weakness_ledger")
    op.drop_table("mock_session_reports")
    op.drop_table("mock_answers")
    op.drop_table("mock_questions")
    op.drop_index(
        "ix_interview_sessions_share_token", table_name="interview_sessions"
    )
    op.drop_column("interview_sessions", "share_token")
    op.drop_column("interview_sessions", "total_cost_inr")
    op.drop_column("interview_sessions", "voice_enabled")
    op.drop_column("interview_sessions", "jd_text")
    op.drop_column("interview_sessions", "level")
    op.drop_column("interview_sessions", "target_role")
