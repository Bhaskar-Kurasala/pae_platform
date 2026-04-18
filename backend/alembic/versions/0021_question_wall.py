"""question_posts + question_votes tables (P3 3B #102)

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-18 00:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "question_posts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "lesson_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "parent_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("body", sa.String(4000), nullable=False),
        sa.Column(
            "upvote_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "flag_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
            ["lesson_id"], ["lessons.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["question_posts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_posts_lesson_id", "question_posts", ["lesson_id"]
    )
    op.create_index(
        "ix_question_posts_author_id", "question_posts", ["author_id"]
    )
    op.create_index(
        "ix_question_posts_parent_id", "question_posts", ["parent_id"]
    )

    op.create_table(
        "question_votes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "post_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "voter_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("kind", sa.String(16), nullable=False),
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
            ["post_id"], ["question_posts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["voter_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "post_id",
            "voter_id",
            "kind",
            name="uq_question_votes_post_voter_kind",
        ),
    )
    op.create_index(
        "ix_question_votes_post_id", "question_votes", ["post_id"]
    )
    op.create_index(
        "ix_question_votes_voter_id", "question_votes", ["voter_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_question_votes_voter_id", "question_votes")
    op.drop_index("ix_question_votes_post_id", "question_votes")
    op.drop_table("question_votes")
    op.drop_index("ix_question_posts_parent_id", "question_posts")
    op.drop_index("ix_question_posts_author_id", "question_posts")
    op.drop_index("ix_question_posts_lesson_id", "question_posts")
    op.drop_table("question_posts")
