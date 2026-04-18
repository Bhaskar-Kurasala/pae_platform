"""socratic_level column on user_preferences (P3 3A-3)

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-18 19:00:00.000000

Adds a 0-3 integer column for graded Socratic intensity. The legacy
`tutor_mode` string stays so the strict-mode overlay continues to fire on
level 3; the migration backfills existing rows so no-one loses their setting:
  - tutor_mode='socratic_strict' → socratic_level=3
  - everything else              → socratic_level=0

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column(
            "socratic_level",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    # Backfill existing rows so toggle-set strict users keep strict intensity.
    op.execute(
        "UPDATE user_preferences SET socratic_level = 3 "
        "WHERE tutor_mode = 'socratic_strict'"
    )
    op.create_check_constraint(
        "ck_user_preferences_socratic_level_range",
        "user_preferences",
        "socratic_level >= 0 AND socratic_level <= 3",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_user_preferences_socratic_level_range",
        "user_preferences",
        type_="check",
    )
    op.drop_column("user_preferences", "socratic_level")
