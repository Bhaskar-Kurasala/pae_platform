"""today screen completion — additive schema for production Today UI

Adds:
  - srs_cards.answer / hint  (canonical reveal text + hint copy)
  - exercises.is_capstone, exercises.pass_score
  - goal_contracts.target_role
  - learning_sessions  (per-user ordinal "Session N")
  - cohort_events  (event log driving the cohort feed)

Strictly additive — no destructive operations. Defaults chosen so existing
rows remain valid without backfill scripts.

Revision ID: 0044_today_screen_completion
Revises: 0043_ai_reviews
Create Date: 2026-04-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0044_today_screen_completion"
down_revision: str | None = "0043_ai_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- srs_cards: answer + hint ---------------------------------------
    op.add_column(
        "srs_cards",
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "srs_cards",
        sa.Column("hint", sa.Text(), nullable=False, server_default=""),
    )

    # --- exercises: capstone flag + per-exercise pass score -------------
    op.add_column(
        "exercises",
        sa.Column(
            "is_capstone",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "exercises",
        sa.Column(
            "pass_score",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("70"),
        ),
    )
    op.add_column(
        "exercises",
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- goal_contracts: structured target role -------------------------
    op.add_column(
        "goal_contracts",
        sa.Column("target_role", sa.String(length=128), nullable=True),
    )

    # --- learning_sessions ----------------------------------------------
    op.create_table(
        "learning_sessions",
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
            index=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "ended_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "ordinal",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "warmup_done_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "lesson_done_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "reflect_done_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
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
        sa.UniqueConstraint(
            "user_id", "ordinal", name="uq_learning_sessions_user_ordinal"
        ),
    )
    op.create_index(
        "ix_learning_sessions_user_started",
        "learning_sessions",
        ["user_id", "started_at"],
    )

    # --- cohort_events --------------------------------------------------
    op.create_table(
        "cohort_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=64), nullable=False, index=True),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("actor_handle", sa.String(length=128), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "payload", sa.JSON(), nullable=True
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "level_slug", sa.String(length=64), nullable=True, index=True
        ),
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
        "ix_cohort_events_kind_occurred",
        "cohort_events",
        ["kind", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_cohort_events_kind_occurred", "cohort_events")
    op.drop_table("cohort_events")

    op.drop_index("ix_learning_sessions_user_started", "learning_sessions")
    op.drop_table("learning_sessions")

    op.drop_column("goal_contracts", "target_role")

    op.drop_column("exercises", "due_at")
    op.drop_column("exercises", "pass_score")
    op.drop_column("exercises", "is_capstone")

    op.drop_column("srs_cards", "hint")
    op.drop_column("srs_cards", "answer")
