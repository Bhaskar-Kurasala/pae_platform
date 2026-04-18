"""lesson.skill_id + exercise.skill_id FKs

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_lessons_skill_id",
        "lessons",
        "skills",
        ["skill_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_lessons_skill_id", "lessons", ["skill_id"])

    op.add_column(
        "exercises",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_exercises_skill_id",
        "exercises",
        "skills",
        ["skill_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_exercises_skill_id", "exercises", ["skill_id"])


def downgrade() -> None:
    op.drop_index("ix_exercises_skill_id", "exercises")
    op.drop_constraint("fk_exercises_skill_id", "exercises", type_="foreignkey")
    op.drop_column("exercises", "skill_id")

    op.drop_index("ix_lessons_skill_id", "lessons")
    op.drop_constraint("fk_lessons_skill_id", "lessons", type_="foreignkey")
    op.drop_column("lessons", "skill_id")
