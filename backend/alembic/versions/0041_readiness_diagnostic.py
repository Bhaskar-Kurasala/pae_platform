"""readiness diagnostic + JD decoder tables

Creates the six tables backing the "Am I Ready?" diagnostic agent and the
JD Decoder agent:

  - readiness_student_snapshots   (denormalized verified-data cache)
  - readiness_diagnostic_sessions (one row per conversation)
  - readiness_diagnostic_turns    (per-message transcript)
  - readiness_verdicts            (headline / evidence / next-action)
  - jd_analyses                   (decoded JD, hash-keyed cache)
  - jd_match_scores               (per-student × JD score)

Cost rows for these agents go to ``agent_invocation_log`` (created by
0040). MockWeaknessLedger from the mock interview stack is reused as the
cross-agent gap memory; no new ledger table here.

Revision ID: 0041_readiness_diagnostic
Revises: 0040_agent_invocation_log
Create Date: 2026-04-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0041_readiness_diagnostic"
down_revision: str | None = "0040_agent_invocation_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- readiness_student_snapshots ---------------------------------
    op.create_table(
        "readiness_student_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("evidence_allowlist", sa.JSON, nullable=False),
        sa.Column(
            "built_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_readiness_student_snapshots_user_id",
        "readiness_student_snapshots",
        ["user_id"],
    )
    op.create_index(
        "ix_readiness_student_snapshots_built_at",
        "readiness_student_snapshots",
        ["built_at"],
    )

    # ---- readiness_diagnostic_sessions -------------------------------
    # The verdict_id FK is created with use_alter=True at the model level
    # because readiness_verdicts is defined later in the same migration.
    # Alembic emits the FK in a separate ALTER TABLE after both tables
    # exist; here we declare the column without an inline FK and add it
    # explicitly afterward.
    op.create_table(
        "readiness_diagnostic_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "readiness_student_snapshots.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column(
            "verdict_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "turns_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "next_action_clicked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "next_action_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_readiness_diagnostic_sessions_user_id",
        "readiness_diagnostic_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_readiness_diagnostic_sessions_started_at",
        "readiness_diagnostic_sessions",
        ["started_at"],
    )

    # ---- readiness_diagnostic_turns ----------------------------------
    op.create_table(
        "readiness_diagnostic_turns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "readiness_diagnostic_sessions.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("metadata_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_readiness_diagnostic_turns_session_id",
        "readiness_diagnostic_turns",
        ["session_id"],
    )
    op.create_index(
        "ix_readiness_diagnostic_turns_created_at",
        "readiness_diagnostic_turns",
        ["created_at"],
    )

    # ---- readiness_verdicts ------------------------------------------
    op.create_table(
        "readiness_verdicts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "readiness_diagnostic_sessions.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("headline", sa.String(280), nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("next_action_intent", sa.String(40), nullable=False),
        sa.Column("next_action_route", sa.String(255), nullable=False),
        sa.Column("next_action_label", sa.String(120), nullable=False),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("validation", sa.JSON, nullable=True),
        sa.Column("sycophancy_flags", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_readiness_verdicts_session_id",
        "readiness_verdicts",
        ["session_id"],
    )

    # Now that both sides of the cycle exist, attach the verdict_id FK.
    op.create_foreign_key(
        "fk_readiness_diagnostic_sessions_verdict_id",
        "readiness_diagnostic_sessions",
        "readiness_verdicts",
        ["verdict_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ---- jd_analyses --------------------------------------------------
    op.create_table(
        "jd_analyses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "jd_hash", sa.String(64), nullable=False, unique=True
        ),
        sa.Column("jd_text_truncated", sa.Text, nullable=False),
        sa.Column("parsed", sa.JSON, nullable=False),
        sa.Column("analysis", sa.JSON, nullable=False),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_jd_analyses_jd_hash",
        "jd_analyses",
        ["jd_hash"],
        unique=True,
    )
    op.create_index(
        "ix_jd_analyses_created_at", "jd_analyses", ["created_at"]
    )

    # ---- jd_match_scores ---------------------------------------------
    op.create_table(
        "jd_match_scores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "jd_analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jd_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "readiness_student_snapshots.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column("score", sa.Integer, nullable=True),
        sa.Column("headline", sa.String(280), nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("next_action_intent", sa.String(40), nullable=False),
        sa.Column("next_action_route", sa.String(255), nullable=False),
        sa.Column("next_action_label", sa.String(120), nullable=False),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("validation", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_jd_match_scores_user_id", "jd_match_scores", ["user_id"]
    )
    op.create_index(
        "ix_jd_match_scores_jd_analysis_id",
        "jd_match_scores",
        ["jd_analysis_id"],
    )
    op.create_index(
        "ix_jd_match_scores_user_jd",
        "jd_match_scores",
        ["user_id", "jd_analysis_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_jd_match_scores_user_jd", table_name="jd_match_scores"
    )
    op.drop_index(
        "ix_jd_match_scores_jd_analysis_id", table_name="jd_match_scores"
    )
    op.drop_index(
        "ix_jd_match_scores_user_id", table_name="jd_match_scores"
    )
    op.drop_table("jd_match_scores")

    op.drop_index("ix_jd_analyses_created_at", table_name="jd_analyses")
    op.drop_index("ix_jd_analyses_jd_hash", table_name="jd_analyses")
    op.drop_table("jd_analyses")

    op.drop_constraint(
        "fk_readiness_diagnostic_sessions_verdict_id",
        "readiness_diagnostic_sessions",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_readiness_verdicts_session_id",
        table_name="readiness_verdicts",
    )
    op.drop_table("readiness_verdicts")

    op.drop_index(
        "ix_readiness_diagnostic_turns_created_at",
        table_name="readiness_diagnostic_turns",
    )
    op.drop_index(
        "ix_readiness_diagnostic_turns_session_id",
        table_name="readiness_diagnostic_turns",
    )
    op.drop_table("readiness_diagnostic_turns")

    op.drop_index(
        "ix_readiness_diagnostic_sessions_started_at",
        table_name="readiness_diagnostic_sessions",
    )
    op.drop_index(
        "ix_readiness_diagnostic_sessions_user_id",
        table_name="readiness_diagnostic_sessions",
    )
    op.drop_table("readiness_diagnostic_sessions")

    op.drop_index(
        "ix_readiness_student_snapshots_built_at",
        table_name="readiness_student_snapshots",
    )
    op.drop_index(
        "ix_readiness_student_snapshots_user_id",
        table_name="readiness_student_snapshots",
    )
    op.drop_table("readiness_student_snapshots")
