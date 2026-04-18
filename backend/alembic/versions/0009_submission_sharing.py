"""shared_with_peers + share_note on exercise_submissions (P2-07)

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-18 05:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "exercise_submissions",
        sa.Column(
            "shared_with_peers",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "exercise_submissions",
        sa.Column("share_note", sa.String(length=500), nullable=True),
    )
    op.create_index(
        "ix_exercise_submissions_shared",
        "exercise_submissions",
        ["exercise_id", "shared_with_peers"],
    )


def downgrade() -> None:
    op.drop_index("ix_exercise_submissions_shared", "exercise_submissions")
    op.drop_column("exercise_submissions", "share_note")
    op.drop_column("exercise_submissions", "shared_with_peers")
