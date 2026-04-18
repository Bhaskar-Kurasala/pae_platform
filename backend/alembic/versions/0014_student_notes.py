"""student_notes table (P3 3A-18)

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-18 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "student_notes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "admin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body_md", sa.Text(), nullable=False),
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
    )
    op.create_index("ix_student_notes_admin_id", "student_notes", ["admin_id"])
    op.create_index(
        "ix_student_notes_student_id", "student_notes", ["student_id"]
    )
    op.create_index(
        "ix_student_notes_created_at", "student_notes", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_student_notes_created_at", "student_notes")
    op.drop_index("ix_student_notes_student_id", "student_notes")
    op.drop_index("ix_student_notes_admin_id", "student_notes")
    op.drop_table("student_notes")
