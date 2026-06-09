"""D15 CP1 — backfill student_role_state for existing users.

Per Pattern 3 (data migrations ship in their own commit so rollback
discipline is clean), this migration is split from the schema+seed
migration 0061. Inserting student_role_state rows is a data operation
on the existing users population — separable from the schema work.

Backfill semantics:

  Every existing user (regardless of soft-delete state, role string on
  the users table, or promoted_at) gets one student_role_state row
  pointing to python_developer. Rationale:

    * python_developer is sequence_order=1 — the entry point for the
      progression. New users default here naturally; existing users
      should land here too because we have no historical signal to
      place them anywhere else (the legacy `users.promoted_to_role`
      column held free-text role strings unrelated to the six-role
      identity sequence).

    * is_deleted users still get a row — the FK has ON DELETE CASCADE,
      so a future hard-delete cleans up automatically; meanwhile, if a
      soft-deleted user is restored, their role state is already there.

    * Idempotent via INSERT ... ON CONFLICT DO NOTHING on the
      student_id UNIQUE constraint, so re-running the migration (e.g.
      after a partial failure or a downgrade-then-upgrade cycle) does
      not duplicate rows.

The legacy `users.promoted_to_role` column (free-text, e.g. "Senior ML
Engineer") and `promoted_at` are NOT consulted here. Those fields are
kept in place for audit/compatibility; their relationship to the six-
role sequence is a CP2/CP3 product question, not a CP1 schema
question. Surface in the CP2 audit if we want to map them.

Revision ID: 0062_role_progression_backfill
Revises: 0061_role_progression_schema
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062_role_progression_backfill"
down_revision: str | None = "0061_role_progression_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Single SQL statement — atomic, idempotent via ON CONFLICT.
    # The role_started_at default (now()) reflects "tracking starts
    # now" rather than "student joined platform N days ago" because
    # we don't have a meaningful start-time signal for the existing
    # population — the role progression itself is net-new.
    op.execute(
        sa.text(
            """
            INSERT INTO student_role_state (student_id, current_role_id)
            SELECT u.id, r.id
            FROM users u
            CROSS JOIN roles r
            WHERE r.slug = 'python_developer'
            ON CONFLICT (student_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    # Drop only rows that we created — i.e. all rows currently in the
    # table, since 0061's downgrade also drops the table. We keep the
    # body explicit so a partial downgrade (this migration only) leaves
    # the schema intact and the data cleared.
    op.execute(sa.text("DELETE FROM student_role_state"))
