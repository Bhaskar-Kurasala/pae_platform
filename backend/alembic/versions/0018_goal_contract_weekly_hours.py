"""goal_contracts.weekly_hours column (P3 3B #5)

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "goal_contracts",
        sa.Column("weekly_hours", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("goal_contracts", "weekly_hours")
