"""add anomaly dismissal table

Revision ID: 0073_anomaly_dismissal
Revises: 0072_agent_task_template
Create Date: 2026-05-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0073_anomaly_dismissal"
down_revision = "0072_agent_task_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "anomaly_dismissal",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("fingerprint", sa.String(length=255), nullable=False),
        sa.Column("rule_type", sa.String(length=64), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dismissed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dismissed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("fingerprint", name="uq_anomaly_dismissal_fingerprint"),
    )
    op.create_index(
        "ix_anomaly_dismissal_fingerprint",
        "anomaly_dismissal",
        ["fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_anomaly_dismissal_fingerprint", table_name="anomaly_dismissal")
    op.drop_table("anomaly_dismissal")
