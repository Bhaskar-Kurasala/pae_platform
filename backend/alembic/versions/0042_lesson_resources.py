"""lesson_resources — polymorphic resources attached to courses/lessons

One row per learnable artifact (notebook, repo, video, pdf, slides, link).
Stores repo-relative ``path`` for git-backed assets and a free-form ``url``
for external ones. Resolution to a Colab/download URL happens in the API
layer, gated by enrollment.

Revision ID: 0042_lesson_resources
Revises: 0041_readiness_diagnostic
Create Date: 2026-04-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0042_lesson_resources"
down_revision: str | None = "0041_readiness_diagnostic"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lesson_resources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("path", sa.String(length=1000), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_lesson_resources_course_id",
        "lesson_resources",
        ["course_id"],
    )
    op.create_index(
        "ix_lesson_resources_lesson_id",
        "lesson_resources",
        ["lesson_id"],
    )
    op.create_index(
        "ix_lesson_resources_course_lesson_order",
        "lesson_resources",
        ["course_id", "lesson_id", "order"],
    )


def downgrade() -> None:
    op.drop_index("ix_lesson_resources_course_lesson_order", table_name="lesson_resources")
    op.drop_index("ix_lesson_resources_lesson_id", table_name="lesson_resources")
    op.drop_index("ix_lesson_resources_course_id", table_name="lesson_resources")
    op.drop_table("lesson_resources")
