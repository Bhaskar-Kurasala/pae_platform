"""tailored_resume + generation_logs + resume.intake_data

Revision ID: 0037_tailored_resume
Revises: 0036_notebook_enhancements
Create Date: 2026-04-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0037_tailored_resume"
down_revision: str | None = "0036_notebook_enhancements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resumes",
        sa.Column("intake_data", sa.JSON(), nullable=True),
    )

    op.create_table(
        "tailored_resumes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "base_resume_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resumes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "jd_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jd_library.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("jd_text", sa.Text(), nullable=False),
        sa.Column("jd_parsed", sa.JSON(), nullable=True),
        sa.Column("intake_answers", sa.JSON(), nullable=True),
        sa.Column("content", sa.JSON(), nullable=True),
        sa.Column("validation", sa.JSON(), nullable=True),
        sa.Column("pdf_url", sa.String(512), nullable=True),
        sa.Column("pdf_blob", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_tailored_resumes_user_id_created_at",
        "tailored_resumes",
        ["user_id", "created_at"],
    )

    op.create_table(
        "generation_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "tailored_resume_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tailored_resumes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event", sa.String(32), nullable=False, index=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_inr", sa.Numeric(10, 4), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("validation_passed", sa.Boolean(), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_generation_logs_user_id_created_at",
        "generation_logs",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_generation_logs_user_id_event",
        "generation_logs",
        ["user_id", "event"],
    )


def downgrade() -> None:
    op.drop_index("ix_generation_logs_user_id_event", table_name="generation_logs")
    op.drop_index("ix_generation_logs_user_id_created_at", table_name="generation_logs")
    op.drop_table("generation_logs")
    op.drop_index("ix_tailored_resumes_user_id_created_at", table_name="tailored_resumes")
    op.drop_table("tailored_resumes")
    op.drop_column("resumes", "intake_data")
