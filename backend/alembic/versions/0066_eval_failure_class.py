"""D17b/ITEM 4.A — add failure_class enum column to agent_evaluations.

Closes sub-item 2 of docs/followups/eval-row-writer-defensive-fix.md
("future redesign could add an explicit failure_class enum").

Why this matters:
  Today every failed eval row lands as `total_score=0.0, passed=False`
  regardless of *why* it failed. Three distinct causes collapse into
  one shape:
    * Critic returned a parsed verdict but score < threshold
    * Critic LLM ran but parsed_ok=False (verdict shape failure;
      reasoning starts with "critic flaked: ")
    * Agent's run() raised before the Critic could score anything
      (the D13 Bug 22 path)
  Plus the success case (`passed=True`).

  The discriminator was hidden in `critic_reasoning` text shape (a
  prefix-substring contract that no DB query can rely on). The new
  failure_class column makes the shape queryable.

Schema choice: TEXT column with a CHECK constraint enforcing the
4-value enum, mirroring how slip_type lives on student_risk_signals
and channel lives on outreach_log. Reasons over a Postgres ENUM type:
  * No extra `CREATE TYPE` migration; ALTER COLUMN later (e.g., adding
    a value) requires only updating the CHECK constraint.
  * SQLAlchemy doesn't need a custom type adapter; a plain str column
    binds cleanly to the Python `EvalFailureClass` str-enum.
  * Matches the project's existing convention for small enum-shaped
    text fields.

Backfill: column is added NULL on existing rows. Pre-D17b rows have
no failure_class signal; backfilling them retroactively would require
re-deriving from `critic_reasoning` text shape (the prefix-substring
contract this column replaces) — fragile and not load-bearing for
forward dashboards. Existing dev DB has 27 agent_evaluations rows;
they remain NULL. New rows from D17b ITEM 4.A onward populate the
field at the writer call sites.

Revision ID: 0066_eval_failure_class
Revises: 0065_users_whatsapp_number
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066_eval_failure_class"
down_revision: str | None = "0065_users_whatsapp_number"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Canonical enum values — keep in sync with EvalFailureClass in
# backend/app/agents/primitives/evaluation.py. Adding a new value
# requires both: a new enum member AND a new migration that drops +
# re-adds the CHECK constraint.
_FAILURE_CLASS_VALUES = (
    "none",
    "below_threshold",
    "critic_flaked",
    "agent_raised",
)


def upgrade() -> None:
    op.add_column(
        "agent_evaluations",
        sa.Column("failure_class", sa.Text(), nullable=True),
    )
    # CHECK enforces the enum at the DB layer. NULL is also accepted
    # for backfill of pre-D17b rows; new writes always supply a value.
    values_sql = ", ".join(f"'{v}'" for v in _FAILURE_CLASS_VALUES)
    op.create_check_constraint(
        "agent_evaluations_failure_class_enum",
        "agent_evaluations",
        f"failure_class IS NULL OR failure_class IN ({values_sql})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "agent_evaluations_failure_class_enum",
        "agent_evaluations",
        type_="check",
    )
    op.drop_column("agent_evaluations", "failure_class")
