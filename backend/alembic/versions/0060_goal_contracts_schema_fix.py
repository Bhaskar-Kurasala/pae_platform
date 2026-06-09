"""D12 / goal-contracts-schema-divergence.md — formal schema resolution.

The D10 CP2 defensive fix (commit 21ff4f6) corrected the query in
agentic_snapshot_service._load_goal_contract to use the real column
names (weekly_hours, not weekly_hours_committed; no expires_at filter).
That fix was intentionally narrow — it eliminated the broken behavior
without committing to the architecturally-intended semantics.

This migration delivers the D12 "proper schema work" decision:

1. ADD expires_at TIMESTAMPTZ NULL to goal_contracts.
   The spec implies active goal contracts have expiry windows (the
   architecture comment referenced it; the course_entitlements table
   already has this column). Adding it now makes the schema match the
   intent. NULL means "no expiry" — existing rows are unaffected.

2. No rename of weekly_hours. The bucket-string convention
   ('3-5', '6-10', '11+') is the correct user-facing representation.
   study_planner reads it as a bucket label, not a float. The
   defensive fix in GoalContractSummary already normalised to str.

3. Update agentic_snapshot_service._load_goal_contract to honour
   expires_at in its WHERE clause once this column exists. The code
   change lands in the same commit as this migration.

Revision ID: 0060_goal_contracts_schema_fix
Revises: 0059_consolidate_legacy_agents
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060_goal_contracts_schema_fix"
down_revision: str | None = "0059_consolidate_legacy_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "goal_contracts",
        sa.Column(
            "expires_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Optional expiry for the goal contract. NULL = no expiry.",
        ),
    )


def downgrade() -> None:
    op.drop_column("goal_contracts", "expires_at")
