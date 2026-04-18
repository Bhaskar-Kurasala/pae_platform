"""growth_snapshots table (P1-C-2)

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-18 02:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "growth_snapshots",
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
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("lessons_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skills_touched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("streak_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("top_concept", sa.String(length=128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
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
            "user_id", "week_ending", name="uq_growth_snapshots_user_week"
        ),
    )
    op.create_index(
        "ix_growth_snapshots_user_id", "growth_snapshots", ["user_id"]
    )
    op.create_index(
        "ix_growth_snapshots_week_ending", "growth_snapshots", ["week_ending"]
    )


def downgrade() -> None:
    op.drop_index("ix_growth_snapshots_week_ending", "growth_snapshots")
    op.drop_index("ix_growth_snapshots_user_id", "growth_snapshots")
    op.drop_table("growth_snapshots")
