"""weekly_intentions table (P3 3B #151)

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weekly_intentions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("week_starting", sa.Date(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(280), nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "week_starting",
            "slot",
            name="uq_weekly_intentions_user_week_slot",
        ),
    )
    op.create_index(
        "ix_weekly_intentions_user_id", "weekly_intentions", ["user_id"]
    )
    op.create_index(
        "ix_weekly_intentions_week_starting",
        "weekly_intentions",
        ["week_starting"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_weekly_intentions_week_starting", "weekly_intentions"
    )
    op.drop_index("ix_weekly_intentions_user_id", "weekly_intentions")
    op.drop_table("weekly_intentions")
