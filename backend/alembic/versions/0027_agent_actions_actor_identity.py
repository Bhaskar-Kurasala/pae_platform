"""agent_actions actor identity columns (E2E-DISC-57)

Revision ID: 0027
Revises: 0026
Create Date: 2026-04-19 16:00:00.000000

Background:
  Admin-triggered agent invocations were indistinguishable from
  student-originated actions in the audit log — no `actor_id`,
  `actor_role`, or impersonation marker. AD8 failed because a
  compliance-grade audit story couldn't attribute a run to a human.

This migration:
  1. Adds `actor_id` (nullable UUID FK to users.id) — the identity
     that initiated the action (admin for manual triggers, student
     for chat-driven calls; NULL for system/cron/webhook).
  2. Adds `actor_role` (nullable string) — "admin" | "student" |
     "system" | "service"; denormalized snapshot that survives a
     future role change on the actor's user row.
  3. Adds `on_behalf_of` (nullable UUID FK to users.id) — populated
     when an admin triggers an agent targeting another user; renders
     as "admin → student" in the audit UI.

No backfill: existing rows are pre-actor-identity and remain NULL,
which the UI renders as "(unknown)" rather than conflating with a
real admin.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_actions",
        sa.Column("actor_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "agent_actions",
        sa.Column("actor_role", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "agent_actions",
        sa.Column(
            "on_behalf_of", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_agent_actions_actor_id_users",
        "agent_actions",
        "users",
        ["actor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_agent_actions_on_behalf_of_users",
        "agent_actions",
        "users",
        ["on_behalf_of"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_actions_actor_id", "agent_actions", ["actor_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_agent_actions_actor_id", table_name="agent_actions")
    op.drop_constraint(
        "fk_agent_actions_on_behalf_of_users", "agent_actions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_agent_actions_actor_id_users", "agent_actions", type_="foreignkey"
    )
    op.drop_column("agent_actions", "on_behalf_of")
    op.drop_column("agent_actions", "actor_role")
    op.drop_column("agent_actions", "actor_id")
