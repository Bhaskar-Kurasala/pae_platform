"""confidence_reports table (P3 3A-7)

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-18 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "confidence_reports",
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
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "value >= 1 AND value <= 5",
            name="ck_confidence_reports_value_range",
        ),
    )
    op.create_index(
        "ix_confidence_reports_user_id", "confidence_reports", ["user_id"]
    )
    op.create_index(
        "ix_confidence_reports_skill_id", "confidence_reports", ["skill_id"]
    )
    op.create_index(
        "ix_confidence_reports_answered_at",
        "confidence_reports",
        ["answered_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_confidence_reports_answered_at", "confidence_reports")
    op.drop_index("ix_confidence_reports_skill_id", "confidence_reports")
    op.drop_index("ix_confidence_reports_user_id", "confidence_reports")
    op.drop_table("confidence_reports")
