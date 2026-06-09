"""add agent runtime config table

Revision ID: 77d8139a3660
Revises: 0071_admin_audit_log
Create Date: 2026-05-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "77d8139a3660"
down_revision: Union[str, Sequence[str], None] = "0071_admin_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_runtime_config",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("agent_runtime_config")
