"""D19.2 / CP1.4 — per-student daily cost ceiling override.

D19.2 D-B: each student has a configurable daily cost ceiling. The
existing ceiling system in `app/services/entitlement_service.py`
resolves a tier-based ceiling (free / paid course tiers). D-B
requires a per-student override that wins over tier defaults so a
specific student can be tightened (suspected adversarial use,
budget concerns) or loosened (paying customer at standard tier with
a one-off allowance) without changing the global tier configuration.

Column: `users.daily_cost_ceiling_inr_override`. Numeric; nullable.

  * NULL (default for all existing users at migration time) →
    `_resolve_cost_ceiling` falls through to the tier-based default.
  * Non-NULL → use this value as the ceiling for this user, ignoring
    tier defaults.

No index needed. Read happens once per agent invocation as part of
`compute_active_entitlements`, always through `user_id` (the PK);
adding an index for a column that's queried by-PK only would be
overhead.

Revision ID: 0067_users_daily_cost_ceiling
Revises: 0066_eval_failure_class
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067_users_daily_cost_ceiling"
down_revision: str | None = "0066_eval_failure_class"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "daily_cost_ceiling_inr_override",
            sa.Numeric(precision=10, scale=2),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "daily_cost_ceiling_inr_override")
