"""add admin audit log table

Revision ID: 0071_admin_audit_log
Revises: 0070_coupons_and_courses_is_featured
Create Date: 2026-05-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0071_admin_audit_log"
down_revision = ("0070_coupons_featured", "4ea695ab911b")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("admin_email", sa.String(length=255), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("before_value", sa.JSON(), nullable=True),
        sa.Column("after_value", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_admin_audit_log_admin_id", "admin_audit_log", ["admin_id"])
    op.create_index("ix_admin_audit_log_action_type", "admin_audit_log", ["action_type"])
    op.create_index("ix_admin_audit_log_resource_id", "admin_audit_log", ["resource_id"])
    op.create_index("ix_admin_audit_log_trace_id", "admin_audit_log", ["trace_id"])
    op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_audit_log_created_at", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_trace_id", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_resource_id", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_action_type", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_admin_id", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
