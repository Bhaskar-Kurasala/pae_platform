"""coupons table + courses.is_featured

Revision ID: 0070
Revises: 0069
Create Date: 2026-05-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0070_coupons_featured"
down_revision = "0069_users_auth_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coupons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("bundle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("percent_off", sa.Integer(), nullable=False),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("redemption_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bundle_id"], ["course_bundles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("code", name="uq_coupons_code"),
    )
    op.create_index("ix_coupons_code", "coupons", ["code"], unique=True)
    op.create_index("ix_coupons_course_id", "coupons", ["course_id"])
    op.create_index("ix_coupons_bundle_id", "coupons", ["bundle_id"])

    op.add_column(
        "courses",
        sa.Column(
            "is_featured",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("courses", "is_featured")
    op.drop_index("ix_coupons_bundle_id", table_name="coupons")
    op.drop_index("ix_coupons_course_id", table_name="coupons")
    op.drop_index("ix_coupons_code", table_name="coupons")
    op.drop_table("coupons")
