# Alembic upgrade-from-base failure at 0023

**Status:** Open — pre-existing issue, NOT introduced by D9.

## Background

Per Track 6 baseline (`docs/audits/track-6-baseline.md` §4.2), running
`alembic upgrade head` against a pristine empty Postgres database fails
at migration 0023:

```
asyncpg.exceptions.DatatypeMismatchError:
foreign key constraint "saved_skill_paths_user_id_fkey"
cannot be implemented
```

Root cause: a VARCHAR/UUID FK type mismatch in 0023, plus a related
data-backfill issue in 0040 that has since been made offline-mode-safe.

## Current handling

CI tolerates the failure as a yellow signal rather than red-blocking
every PR (`.github/workflows/ci.yml:81-88`). Existing dev environments
have already run through 0023 successfully (the broken FK was emitted
under a permissive Postgres + sqlalchemy combo at the time, and is now
fixed in-place by later migrations, so an established DB stays
consistent — only `upgrade-from-base` is broken).

## Fix

A dedicated migrations-cleanup PR is required to repair 0023's FK
column type before fresh-DB bootstraps work end-to-end. Out of scope
for D9.

## D9 contribution

D9 added migrations 0055, 0056, 0057, 0058 (Supervisor audit surface,
curriculum graph schema, entitlement tier infrastructure, safety
incidents). These four migrations round-trip cleanly within their
range (0058 ↔ 0054) and are NOT contributors to the
upgrade-from-base issue. The 0023 break still occurs at the same
point in the chain regardless of whether D9's migrations are present.

Verification: round-trip `alembic downgrade 0054_agentic_os_primitives`
followed by `alembic upgrade head` was performed against the live
`platform` database during D9 Checkpoint 1 and completed without
errors. All 8 new tables, 1 materialized view, 4 column additions,
and 20 indexes were correctly removed and re-applied.

## Related

- `docs/audits/track-6-baseline.md` §4.2 — the original baseline
  finding
- `.github/workflows/ci.yml:81-88` — CI tolerance comment
