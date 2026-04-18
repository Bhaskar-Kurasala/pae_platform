"""peer_review_assignments table (P3 3B #101)

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-18 00:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "peer_review_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "submission_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "reviewer_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("comment", sa.String(2000), nullable=True),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["exercise_submissions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "submission_id",
            "reviewer_id",
            name="uq_peer_review_submission_reviewer",
        ),
    )
    op.create_index(
        "ix_peer_review_assignments_submission_id",
        "peer_review_assignments",
        ["submission_id"],
    )
    op.create_index(
        "ix_peer_review_assignments_reviewer_id",
        "peer_review_assignments",
        ["reviewer_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_peer_review_assignments_reviewer_id",
        "peer_review_assignments",
    )
    op.drop_index(
        "ix_peer_review_assignments_submission_id",
        "peer_review_assignments",
    )
    op.drop_table("peer_review_assignments")
