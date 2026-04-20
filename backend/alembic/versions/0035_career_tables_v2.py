"""career tables v2 — jd_library, interview_sessions, story_bank + resume columns

Revision ID: 0035_career_tables_v2
Revises: 0034_notebook_entries
Create Date: 2026-04-20

Adds three new tables for the expanded career module:
  - jd_library: saved job descriptions per user with fit-score verdict
  - interview_sessions: mock interview sessions with per-answer scores
  - story_bank: STAR stories for behavioral interview preparation

Also adds three columns to the existing `resumes` table:
  - bullets: JSON list of evidence-grounded resume bullets
  - ats_keywords: JSON list of extracted ATS keywords
  - verdict: overall resume fit verdict (strong_fit|good_fit|needs_work)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0035_career_tables_v2"
down_revision: str | None = "0034_notebook_entries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. jd_library — saved job descriptions per user
    # ------------------------------------------------------------------
    op.create_table(
        "jd_library",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("jd_text", sa.Text(), nullable=False),
        sa.Column("last_fit_score", sa.Float(), nullable=True),
        # verdict: apply | skill_up | skip
        sa.Column("verdict", sa.String(20), nullable=True),
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
    op.create_index("ix_jd_library_user_id", "jd_library", ["user_id"])

    # ------------------------------------------------------------------
    # 2. interview_sessions — mock interview sessions
    # ------------------------------------------------------------------
    op.create_table(
        "interview_sessions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # mode: behavioral | technical | system_design
        sa.Column("mode", sa.String(30), nullable=False),
        # status: active | completed
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("questions_asked", sa.JSON(), nullable=True),
        sa.Column("scores", sa.JSON(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
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
    op.create_index("ix_interview_sessions_user_id", "interview_sessions", ["user_id"])

    # ------------------------------------------------------------------
    # 3. story_bank — STAR stories for behavioral interviews
    # ------------------------------------------------------------------
    op.create_table(
        "story_bank",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("situation", sa.Text(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=True),
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
    op.create_index("ix_story_bank_user_id", "story_bank", ["user_id"])

    # ------------------------------------------------------------------
    # 4. Add columns to existing `resumes` table
    # ------------------------------------------------------------------
    op.add_column("resumes", sa.Column("bullets", sa.JSON(), nullable=True))
    op.add_column("resumes", sa.Column("ats_keywords", sa.JSON(), nullable=True))
    # verdict: strong_fit | good_fit | needs_work
    op.add_column("resumes", sa.Column("verdict", sa.String(20), nullable=True))


def downgrade() -> None:
    # Remove added columns from resumes
    op.drop_column("resumes", "verdict")
    op.drop_column("resumes", "ats_keywords")
    op.drop_column("resumes", "bullets")

    # Drop new tables (reverse order of creation)
    op.drop_index("ix_story_bank_user_id", table_name="story_bank")
    op.drop_table("story_bank")

    op.drop_index("ix_interview_sessions_user_id", table_name="interview_sessions")
    op.drop_table("interview_sessions")

    op.drop_index("ix_jd_library_user_id", table_name="jd_library")
    op.drop_table("jd_library")
