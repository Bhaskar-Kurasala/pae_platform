# Migration chain fresh-DB rebuildability — discipline

**Status:** Open. Discipline / process. No code change pending — this is a
checklist register for migration-author flow.
**Origin:** D18 Phase A CP2 (2026-05-08). Surfaced via the chain survey
that built `playwright_test_template` from migration 0001 forward on a
fresh Postgres database.
**Created:** 2026-05-08 (D18 Phase A CP2 closure).

## What this is

Migrations drift from current model state the same way docs do. The dev
DB has been migrated incrementally over 14+ months; nobody has rebuilt
it from scratch in months. As a result, three migrations broke when
replayed against a fresh Postgres:

- **0023** — `saved_skill_paths` declared `id`/`user_id` as
  `String(36)` while the FK target (`users.id`) is `UUID`. Postgres
  rejected the FK with a type-mismatch error. Forward-fixed at CP2 to
  use `UUID(as_uuid=True)`.
- **0024** — `feedback` table declared `user_id` as
  `Column(..., index=True)` AND added an explicit `op.create_index`
  with the same auto-generated name. Replay collided on the duplicate
  index name. Forward-fixed at CP2 by dropping the inline
  `index=True`.
- **0025** — `reconcile_runtime_state` ended with
  `Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)`. At
  0025's author time `Base.metadata` had ~13 future-table targets;
  today it has 59. `create_all` on a fresh DB at rev 0024 forward-
  references future schema (e.g., `agent_memory.scope` references the
  `agent_memory_scope` ENUM created by 0054) and crashes with
  `UndefinedObjectError`. Forward-fixed at CP2 by dropping the
  `create_all` block; the four `ADD COLUMN IF NOT EXISTS` defenses
  remain (idempotent on canonical fresh DBs, defensive on any
  hypothetical environment still in the original drift state).

The investigation report at
`docs/architecture/d18-cp2-migration-0025-investigation.md` documents
the full evidence chain for 0025 specifically.

## The discipline

**Every new alembic migration must be replayed end-to-end against a
fresh Postgres before merge.** Not "alembic upgrade head against the
dev DB" (which only runs the new revision against an already-migrated
DB) — actually `CREATE DATABASE foo; alembic upgrade head` against
`foo`.

Concretely:

```bash
# 1. Drop + create a scratch DB on the dev Postgres instance.
docker compose exec -T db psql -U postgres -c \
  "DROP DATABASE IF EXISTS migration_check; CREATE DATABASE migration_check"

# 2. Run alembic against it. DATABASE_URL override is required;
#    POSTGRES_DB alone won't work because alembic env.py reads
#    DATABASE_URL first (Pattern 23 finding, see
#    backend/tests/playwright/db/create_template.py docstring).
docker compose exec -T \
  -e DATABASE_URL='postgresql+asyncpg://postgres:postgres@db:5432/migration_check' \
  backend uv run alembic upgrade head

# 3. Drop the scratch DB.
docker compose exec -T db psql -U postgres -c \
  "DROP DATABASE migration_check"
```

**Or** — equivalently and preferred — re-run
`backend/tests/playwright/db/create_template.py` after merging a
migration. That script does the same chain replay end-to-end + asserts
seed-state invariants (6 roles / 5 transitions / 11 courses / 11
backfilled). If the create_template script breaks, the chain is broken.

## Why this matters

- **Production migration risk** — production environments will only
  ever run migrations forward from their current state. A migration
  that crashes on a fresh DB but succeeds on the dev DB is a latent
  prod bomb the day we cut a fresh production DB or recover from
  backup.
- **CI determinism** — D18 Phase A's `playwright_test_template`
  rebuilds from scratch every time `create_template.py` runs. A
  broken chain breaks the test infrastructure.
- **Pattern 22 (spec/schema reconciliation)** — every drifted migration
  is an instance of Pattern 22. The discipline above is the
  preventative; CP2's three forward-fixes are the curative.

## Operational hooks

- **Alembic generation flow** — when running `alembic revision
  --autogenerate -m '...'`, follow up immediately with the fresh-DB
  replay above. Don't merge until it passes.
- **CI gate (future)** — D18 Phase A or B should add a CI job that
  rebuilds `playwright_test_template` from scratch on every PR
  touching `backend/alembic/versions/`. That way a broken migration
  fails CI immediately, not weeks later when someone tries to bootstrap
  a new environment.
- **Pre-merge review** — for any migration PR, the reviewer checks
  that the author has either (a) re-run `create_template.py` locally
  and posted the run output, or (b) included evidence the fresh-DB
  replay was performed. "It works on my dev DB" is not sufficient
  evidence.

## Cross-references

- `docs/architecture/d18-cp2-migration-0025-investigation.md` — full
  investigation that surfaced the 0025 forward-fix, including the
  three-investigation evidence chain.
- `backend/alembic/versions/0023_saved_skill_path.py` — forward-fix
  docstring documenting the type-mismatch drift.
- `backend/alembic/versions/0024_feedback_table.py` — forward-fix
  documenting the duplicate-index drift.
- `backend/alembic/versions/0025_reconcile_runtime_state.py` — forward-
  fix documenting the create_all retirement.
- `backend/tests/playwright/db/create_template.py` — canonical fresh-
  DB rebuild driver; running it is the operational discipline.
