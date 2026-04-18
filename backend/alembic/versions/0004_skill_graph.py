"""skill graph: skills, skill_edges, user_skill_states

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="1"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_skills_slug"),
    )
    op.create_index("ix_skills_slug", "skills", ["slug"])

    op.create_table(
        "skill_edges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("from_skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("edge_type", sa.String(16), nullable=False),
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
            ["from_skill_id"], ["skills.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["to_skill_id"], ["skills.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_skill_id", "to_skill_id", "edge_type",
            name="uq_skill_edges_triple",
        ),
        sa.CheckConstraint(
            "from_skill_id <> to_skill_id",
            name="ck_skill_edges_no_self_loop",
        ),
    )
    op.create_index("ix_skill_edges_from", "skill_edges", ["from_skill_id"])
    op.create_index("ix_skill_edges_to", "skill_edges", ["to_skill_id"])

    op.create_table(
        "user_skill_states",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "mastery_level", sa.String(16), nullable=False, server_default="unknown"
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("last_touched_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "skill_id", name="uq_user_skill_states_user_skill"
        ),
    )
    op.create_index(
        "ix_user_skill_states_user_id", "user_skill_states", ["user_id"]
    )
    op.create_index(
        "ix_user_skill_states_skill_id", "user_skill_states", ["skill_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_skill_states_skill_id", "user_skill_states")
    op.drop_index("ix_user_skill_states_user_id", "user_skill_states")
    op.drop_table("user_skill_states")
    op.drop_index("ix_skill_edges_to", "skill_edges")
    op.drop_index("ix_skill_edges_from", "skill_edges")
    op.drop_table("skill_edges")
    op.drop_index("ix_skills_slug", "skills")
    op.drop_table("skills")
