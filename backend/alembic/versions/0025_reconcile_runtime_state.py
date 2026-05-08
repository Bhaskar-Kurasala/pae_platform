"""reconcile runtime state (E2E-DISC-9 recovery)

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-19 00:00:00.000000

A no-op on a clean DB, self-healing on a drifted one.

Original April-2026 context (E2E-DISC-9 in docs/E2E-TEST-TRACKER.md):
  Some live environments were bootstrapped via SQLAlchemy's
  `create_all()` before the Alembic chain was consistently run. Those
  DBs ended up with most tables in place but `alembic_version` stamped
  at an earlier head (e.g. 0009) while the models had moved on to
  0024. Attempting `alembic upgrade head` on such a DB crashed on
  duplicate-index / duplicate-table errors from 0010-0024.

  The original migration body had two halves:
    1. ALTER TABLE ... ADD COLUMN IF NOT EXISTS for 4 specific columns
       (goal_contracts.weekly_hours, reflections.kind,
        user_preferences.socratic_level,
        exercise_submissions.self_explanation).
    2. `Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)`
       to backfill 13 specific tables enumerated in the E2E-DISC-9
       fix list (confidence_reports, conversation_memory,
       daily_intentions, feedback, interview_questions,
       peer_review_assignments, question_posts, question_votes,
       resumes, saved_skill_paths, student_misconceptions,
       student_notes, weekly_intentions).

D18 Phase A CP2 (2026-05-08) — `create_all` block retired:

  The chain survey for D18's playwright_test_template build surfaced
  that 0025's `create_all` block had become **actively harmful** on
  fresh DBs. Three independent investigations confirmed:

    1. All 13 original recovery tables AND all 4 original recovery
       columns are now created by canonical migrations 0010-0024 on
       a fresh DB (verified at investigation time on rev 0024 of a
       fresh `inv_0025` Postgres database).
    2. `Base.metadata` has grown from ~13 future-table targets at
       0025's author time to **59 future-table targets today** (model
       graph grew through migrations 0026-0066). `create_all` on a
       fresh DB now tries to materialize all 92 model-declared tables;
       checkfirst=True skips the 34 that exist at rev 0024 but
       attempts the other 58 — including `agent_memory` whose `scope`
       column references the `agent_memory_scope` Postgres ENUM that
       isn't created until migration 0054. The forward-reference fails
       with `UndefinedObjectError: type "agent_memory_scope" does not
       exist`.
    3. The 14+-month-old original drift scenario has no documented
       re-occurrence; any environment still in that state has either
       been recovered manually or rebuilt from clean migrations.

  Forward-only fix at D18 Phase A CP2: drop the create_all block;
  keep the four ADD COLUMN IF NOT EXISTS statements. The column-add
  statements remain idempotent on canonical fresh DBs (no-op; columns
  already created by migrations 0007/0017/0011/0015) AND defensive
  on any hypothetical environment still in the original drift state.
  The 13 recovery tables are now load-borne by canonical 0010-0024
  on fresh DBs; on a still-drifted environment, advancing past 0025
  to 0026+ creates them via canonical paths.

  See `docs/architecture/d18-cp2-migration-0025-investigation.md` for
  the full three-investigation evidence chain. Pattern 22 reinforced:
  migrations drift from current model state the same way docs do;
  every new migration must be tested against a fresh Postgres before
  merge — registered as discipline at
  `docs/followups/migration-chain-fresh-db-rebuildability.md`.

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
    # Idempotent on canonical fresh DBs (columns created by earlier
    # migrations); defensive on any environment still in the original
    # April-2026 drift state.
    "ALTER TABLE goal_contracts ADD COLUMN IF NOT EXISTS weekly_hours VARCHAR(16)",
    "ALTER TABLE reflections ADD COLUMN IF NOT EXISTS kind VARCHAR(32) NOT NULL DEFAULT 'day_end'",
    "ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS socratic_level INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE exercise_submissions ADD COLUMN IF NOT EXISTS self_explanation TEXT",
]


def upgrade() -> None:
    # Apply column-level reconciliations (always safe — IF NOT EXISTS).
    # See module docstring for the original E2E-DISC-9 recovery scope.
    for stmt in _ADD_COLUMN_STATEMENTS:
        op.execute(stmt)

    # The original `Base.metadata.create_all(bind=op.get_bind(),
    # checkfirst=True)` block was DROPPED at D18 Phase A CP2
    # (2026-05-08). It became actively harmful on fresh DBs because
    # the model graph grew past what existed at 0025's author time;
    # create_all now forward-references future schema state (e.g.,
    # agent_memory.scope -> agent_memory_scope ENUM created by 0054)
    # and fails with UndefinedObjectError. The original recovery
    # contract (13 tables for E2E-DISC-9) is now satisfied by
    # canonical migrations 0010-0024. See the module docstring + the
    # investigation report at
    # docs/architecture/d18-cp2-migration-0025-investigation.md.


def downgrade() -> None:
    # Intentionally a no-op. This migration is a reconciliation and does not
    # track which columns/tables it actually created at upgrade time, so a
    # symmetric downgrade would risk deleting data that predates 0025.
    pass
