"""srs_cards table (P2-05)

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-18 05:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "srs_cards",
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
        sa.Column("concept_key", sa.String(length=128), nullable=False),
        sa.Column("prompt", sa.String(length=512), nullable=False, server_default=""),
        sa.Column(
            "ease_factor",
            sa.Float(),
            nullable=False,
            server_default=sa.text("2.5"),
        ),
        sa.Column(
            "interval_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "repetitions",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
            "user_id", "concept_key", name="uq_srs_cards_user_concept"
        ),
    )
    op.create_index("ix_srs_cards_user_id", "srs_cards", ["user_id"])
    op.create_index("ix_srs_cards_concept_key", "srs_cards", ["concept_key"])
    op.create_index("ix_srs_cards_next_due_at", "srs_cards", ["next_due_at"])


def downgrade() -> None:
    op.drop_index("ix_srs_cards_next_due_at", "srs_cards")
    op.drop_index("ix_srs_cards_concept_key", "srs_cards")
    op.drop_index("ix_srs_cards_user_id", "srs_cards")
    op.drop_table("srs_cards")
