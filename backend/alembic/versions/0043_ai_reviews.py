"""ai_reviews — persisted senior-engineer reviews tied to /practice

Stores every senior_engineer review the user requests via /practice/review.
problem_id is the exercise being reviewed; nullable so future scratchpad
reviews can attach without a problem.

Revision ID: 0043_ai_reviews
Revises: 0042_lesson_resources
Create Date: 2026-04-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0043_ai_reviews"
down_revision: str | None = "0042_lesson_resources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_reviews",
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
            "problem_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("code_snapshot", sa.Text(), nullable=False),
        sa.Column("review", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_ai_reviews_user_id",
        "ai_reviews",
        ["user_id"],
    )
    op.create_index(
        "ix_ai_reviews_user_problem_created",
        "ai_reviews",
        ["user_id", "problem_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_reviews_user_problem_created", table_name="ai_reviews")
    op.drop_index("ix_ai_reviews_user_id", table_name="ai_reviews")
    op.drop_table("ai_reviews")
