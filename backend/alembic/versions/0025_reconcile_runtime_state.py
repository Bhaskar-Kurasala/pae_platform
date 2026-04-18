"""reconcile runtime state (E2E-DISC-9 recovery)

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-19 00:00:00.000000

A no-op on a clean DB, self-healing on a drifted one.

Context:
  Some live environments were bootstrapped via SQLAlchemy's `create_all()`
  before the Alembic chain was consistently run. Those DBs ended up with
  most tables in place but `alembic_version` stamped at an earlier head
  (e.g. 0009) while the models had moved on to 0024. Attempting
  `alembic upgrade head` on such a DB crashed on duplicate-index /
  duplicate-table errors from 0010-0024.

What this migration does:
  - Uses `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` so the
    operations are safe on both clean and drifted databases.
  - Covers only the additive surface area where drift was observed in the
    E2E sweep (see E2E-DISC-9 in docs/E2E-TEST-TRACKER.md):
      * Missing columns: goal_contracts.weekly_hours,
        reflections.kind, user_preferences.socratic_level,
        exercise_submissions.self_explanation.
      * Missing tables covered by 0010-0024 are created defensively via the
        model metadata (only those whose CREATE TABLE is idempotent-safe).

Downgrade: no-op. This migration only adds; it does not remove.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ADD_COLUMN_STATEMENTS: list[str] = [
    # E2E-DISC-9: onboarding 500s because of these specific column gaps.
    "ALTER TABLE goal_contracts ADD COLUMN IF NOT EXISTS weekly_hours VARCHAR(16)",
    "ALTER TABLE reflections ADD COLUMN IF NOT EXISTS kind VARCHAR(32) NOT NULL DEFAULT 'day_end'",
    "ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS socratic_level INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE exercise_submissions ADD COLUMN IF NOT EXISTS self_explanation TEXT",
]


def upgrade() -> None:
    # 1. Apply column-level reconciliations (always safe — IF NOT EXISTS).
    for stmt in _ADD_COLUMN_STATEMENTS:
        op.execute(stmt)

    # 2. Apply table-level reconciliations by calling `Base.metadata.create_all`
    #    with checkfirst=True. This never drops or alters existing tables; it
    #    only creates the ones missing. Safe to run repeatedly.
    #
    #    We import lazily so Alembic's own env.py doesn't pay the cost on
    #    unrelated upgrades, and so a hypothetical future model removal
    #    doesn't break this historical migration.
    import importlib
    import pkgutil

    from app.core.database import Base
    import app.models as _models_pkg

    for _, module_name, _ in pkgutil.walk_packages(
        _models_pkg.__path__, _models_pkg.__name__ + "."
    ):
        try:
            importlib.import_module(module_name)
        except Exception:  # pragma: no cover - tolerate partial model loads
            pass

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    # Intentionally a no-op. This migration is a reconciliation and does not
    # track which columns/tables it actually created at upgrade time, so a
    # symmetric downgrade would risk deleting data that predates 0025.
    pass
