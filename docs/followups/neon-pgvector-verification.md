# Follow-up: verify pgvector on Neon before applying 0054 in prod

**Owner:** _unassigned — assign whoever runs prod migrations._
**Status:** open
**Created:** 2026-05-01
**Triggered by:** `feat(agentic-os): primitives layer` — migration
`0054_agentic_os_primitives.py` is the first migration that depends
on pgvector.

## Context

`0054_agentic_os_primitives` runs `CREATE EXTENSION IF NOT EXISTS
vector` and creates `agent_memory.embedding vector(1536)`. The
extension is the only thing standing between a clean `alembic upgrade
head` and a 2 AM page on the next prod deploy.

Dev was already aligned in the same PR — `docker-compose.yml` `db`
service was swapped from `postgres:16-alpine` to
`pgvector/pgvector:pg16` (pinned to digest
`sha256:7d400e340efb42f4d8c9c12c6427adb253f726881a9985d2a471bf0eed824dff`).

Prod runs on **Neon Postgres (us-east-1)**. Neon supports pgvector on
every plan and the migration's `CREATE EXTENSION IF NOT EXISTS`
*should* succeed automatically — but this needs a one-time human
verification before we run the migration against the prod DSN.

## What to verify

1. Connect to prod:
   ```bash
   psql "$NEON_DATABASE_URL"
   ```

2. Confirm pgvector is on the allowlist:
   ```sql
   SELECT name, default_version
   FROM pg_available_extensions
   WHERE name = 'vector';
   ```
   Expect one row, version `>= 0.5`.

3. Confirm the migration role has `CREATE` on the database:
   ```sql
   SELECT has_database_privilege(
     current_user, current_database(), 'CREATE'
   );
   ```
   Expect `t`. If `f`:
   ```sql
   -- Run as DB owner
   GRANT CREATE ON DATABASE <db> TO <migration_role>;
   ```

## Why this isn't auto-resolved by the migration

`CREATE EXTENSION` requires a role with appropriate privileges. In
some Neon setups a least-privilege migration role does not have it by
default. Cheaper to verify once and grant explicitly than to hit a
deploy failure mid-rollout.

## Done when

- [ ] pgvector confirmed available on prod DB
- [ ] Migration role confirmed to have `CREATE` privilege
- [ ] (Optional) `CREATE EXTENSION vector;` run pre-emptively as DB
      owner so the migration's `IF NOT EXISTS` is a no-op

## References

- Migration: [`backend/alembic/versions/0054_agentic_os_primitives.py`](../../backend/alembic/versions/0054_agentic_os_primitives.py)
- Dev parity: [`docker-compose.yml`](../../docker-compose.yml) — `db` service
- Neon docs: <https://neon.tech/docs/extensions/pgvector>

## Disposition

When complete, leave the file in place and add a "Resolved
YYYY-MM-DD by @user" line under Status above. Don't delete the file
— the trail of resolved follow-ups is itself useful.
