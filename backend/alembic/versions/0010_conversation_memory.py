"""conversation_memory table (P3 3A-2)

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-18 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_memory",
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
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
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
            "user_id", "skill_id", name="uq_conversation_memory_user_skill"
        ),
    )
    op.create_index(
        "ix_conversation_memory_user_id", "conversation_memory", ["user_id"]
    )
    op.create_index(
        "ix_conversation_memory_skill_id", "conversation_memory", ["skill_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_memory_skill_id", "conversation_memory")
    op.drop_index("ix_conversation_memory_user_id", "conversation_memory")
    op.drop_table("conversation_memory")
