# Follow-up: dev DB image swapped to pgvector/pgvector:pg16

**Owner:** team-wide notice — paste the section below into the team
channel before anyone else pulls main.
**Status:** open until acknowledged in #engineering
**Created:** 2026-05-01

## Why

Migration `0054_agentic_os_primitives` (Agentic OS primitives layer)
needs the pgvector extension. The previous dev DB image,
`postgres:16-alpine`, did not ship the pgvector binaries, so the
migration's `CREATE EXTENSION IF NOT EXISTS vector` fails on first
run against alpine.

The `db` service in `docker-compose.yml` is now pinned to:

```
pgvector/pgvector:pg16@sha256:7d400e340efb42f4d8c9c12c6427adb253f726881a9985d2a471bf0eed824dff
```

Same Postgres 16 major version, same data dir layout, just adds the
extension binaries. Existing pgdata volumes carry over without a
re-init.

## Channel message — paste verbatim

> 📌 **Heads up: dev DB image just changed**
>
> `docker-compose.yml` `db` service swapped from `postgres:16-alpine`
> to `pgvector/pgvector:pg16` (pinned to digest). Same Postgres 16
> major version, just adds the pgvector extension binaries which
> migration 0054 (Agentic OS primitives layer) needs.
>
> **What you need to do after pulling main:**
>
> ```bash
> docker compose pull db
> docker compose up -d db
> docker compose exec backend uv run alembic upgrade head
> ```
>
> ⚠️ **Do NOT run `docker compose down -v`** — that wipes pgdata.
> Plain `down && up -d` (or `up -d` alone) is fine; the volume is
> preserved across the image swap because the Postgres major version
> is identical.
>
> If your dev DB looks empty after the swap, ping me before running
> anything destructive — most likely the volume mount drifted, not
> data loss.
>
> **Affected:** anyone who pulls main and runs the dev stack.
> **Not affected:** prod Neon deploy (pgvector is on Neon's allowlist
> already; tracking issue:
> `docs/followups/neon-pgvector-verification.md`).

## Done when

- [ ] Message posted in #engineering
- [ ] At least one teammate confirms their dev DB came up clean
      after pulling

## Disposition

When complete, mark Status above as "Acknowledged YYYY-MM-DD". Leave
the file — short paper trail is cheap.
