"""student_misconceptions table (P3 3A-6)

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-18 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "student_misconceptions",
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
        sa.Column("topic", sa.Text(), nullable=False, server_default=""),
        sa.Column("student_assertion", sa.Text(), nullable=False),
        sa.Column("tutor_correction", sa.Text(), nullable=False),
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
        "ix_student_misconceptions_user_id", "student_misconceptions", ["user_id"]
    )
    op.create_index(
        "ix_student_misconceptions_created_at",
        "student_misconceptions",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_student_misconceptions_created_at", "student_misconceptions"
    )
    op.drop_index("ix_student_misconceptions_user_id", "student_misconceptions")
    op.drop_table("student_misconceptions")
