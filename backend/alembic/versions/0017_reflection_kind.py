"""reflections.kind column (P3 3A-12)

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-18 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reflections",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default="day_end",
        ),
    )


def downgrade() -> None:
    op.drop_column("reflections", "kind")
