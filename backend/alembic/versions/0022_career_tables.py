"""career tables — resumes and interview_questions (#168 #169)

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-18 21:00:00.000000

Creates two new tables for the career module:
  - resumes: per-user AI-generated professional summary + LinkedIn blurb
  - interview_questions: searchable bank of technical/behavioural questions

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resumes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False, server_default="My Resume"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("skills_snapshot", sa.JSON(), nullable=True),
        sa.Column("linkedin_blurb", sa.Text(), nullable=True),
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
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])

    op.create_table(
        "interview_questions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_tags", sa.JSON(), nullable=True),
        sa.Column("difficulty", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_hint", sa.Text(), nullable=True),
        sa.Column("category", sa.String(50), nullable=False, server_default="technical"),
    )


def downgrade() -> None:
    op.drop_table("interview_questions")
    op.drop_index("ix_resumes_user_id", table_name="resumes")
    op.drop_table("resumes")
