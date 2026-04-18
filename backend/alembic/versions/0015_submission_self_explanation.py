"""exercise_submissions.self_explanation (P3 3A-9)

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-18 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "exercise_submissions",
        sa.Column("self_explanation", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("exercise_submissions", "self_explanation")
