"""feedback table (3B #177)

Revision ID: 0017
Revises: 0011
Create Date: 2026-04-18 19:00:00.000000

Adds a `feedback` table for the floating feedback widget.
Submissions can be anonymous (user_id nullable).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("route", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("sentiment", sa.String(20), nullable=True),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_user_id", table_name="feedback")
    op.drop_table("feedback")
