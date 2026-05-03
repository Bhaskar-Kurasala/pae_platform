# goal_contracts schema divergence — D9 foundation bug found during D10

**Status:** Defensive fix shipped in D10 Checkpoint 2 sign-off
(commit `<hash>` — to be filled at commit time). Proper schema work
deferred to **D12 (career bundle / study_planner)** per Pass 3c E4.
**Created:** 2026-05-03 (D10 Checkpoint 2 sign-off, after smoke-test
investigation).
**Cross-references:** Pass 3b §3.1 (architecture spec gap), Pass 3c E4
(study_planner future home for proper goal contract semantics).

## What we found

The D9-shipped `agentic_snapshot_service._load_goal_contract` queries
columns that **have never existed** on the `goal_contracts` table:

```sql
SELECT weekly_hours_committed, target_role, expires_at
FROM goal_contracts
WHERE user_id = :uid
  AND (expires_at IS NULL OR expires_at > now())
ORDER BY created_at DESC
LIMIT 1
```

Two bugs compounded:

1. **Wrong column name.** The real column is `weekly_hours` (no
   `_committed` suffix), `String(16)`, added in
   [migration 0018](../../backend/alembic/versions/0018_goal_contract_weekly_hours.py).
   `weekly_hours_committed` was never migrated.
2. **Nonexistent column.** No migration through 0058 adds
   `expires_at` to `goal_contracts`. The column exists on
   `course_entitlements` (migration 0057) — likely the source of
   D9's confusion.

Beyond the column-name mistakes, a **second-order asyncpg
transaction-poisoning bug** compounded the impact:

The function had a `try/except Exception` block intended as
"fail-soft on column-not-found" — and at the Python level it did
catch the `UndefinedColumnError` and return `None`. But asyncpg
marks the entire transaction as failed at the protocol level when
any single statement errors, regardless of whether the Python
caller catches the exception. The next statement on the same
session — typically the `agent_call_chain` INSERT inside
`call_agent` — hit `InFailedSQLTransactionError` and aborted the
whole dispatch path. The Python-level catch was masking the bug
within the snapshot service while the cascade broke the
orchestrator one layer up.

## Why D9's manual smoke didn't catch it

Three contributing factors, documented for posterity:

1. **The architecture spec didn't pin field names.** Pass 3b §3.1
   lists `active_goal_contract: GoalContractSummary | None  # weekly
   hours, target role` — the comment names the concept, not the
   exact column names. D9 invented the schema field names
   (`weekly_hours_committed: float | None`, `expires_at: datetime |
   None`) without cross-checking against the actual model + migrations.
   The architecture-spec gap and the implementation-shortcut
   compounded.

2. **D9's smoke didn't exercise the failing path.** The original
   manual smoke seeded an entitlement, hit the canonical agentic
   endpoint as Learning Coach, saw a tutor-shaped response. Either
   the snapshot was Redis-cached on a follow-up, OR D9's test student
   had no `goal_contracts` row, OR the smoke didn't run with a fresh
   session. asyncpg validates column names at parse time, so the
   query fails before any row check — meaning even an empty result
   set won't save you.

3. **The `float()` cast on row[0] was a second latent bug.** The
   real `weekly_hours` column stores bucket strings (`"3-5"`,
   `"6-10"`, `"11+"` per
   [schemas/goal_contract.py WeeklyHours](../../backend/app/schemas/goal_contract.py#L15)).
   Even if D9 had spelled the column name correctly, `float("3-5")`
   would have raised `ValueError` on the first non-null result.
   Two compounding mistakes — wrong column name + wrong type — that
   would have surfaced the first time anyone with a populated
   `goal_contracts` row hit the canonical agentic endpoint.

## Production state

Migrations 0002, 0018, 0025, 0044 are all in
`backend/alembic/versions/` and apply on any `alembic upgrade head`.
**Production has the same schema as dev.** The bug exists in
production identically; it just hasn't been exercised because:

- The canonical `/api/v1/agentic/{flow}/chat` endpoint is brand new
  (D9-shipped) and probably has very low traffic
- Real students who hit it likely have a `goal_contracts` row, so
  the failed-SQL path fires regardless of row presence (asyncpg
  does column-name validation at parse time, not row-by-row)
- The Python `try/except` returned `None` quietly so observability
  didn't flag it as an error

## Defensive fix (D10 Checkpoint 2 sign-off / Commit 5)

Three-file change + 1 test pinning the rollback contract:

1. **[`schemas/supervisor.py`](../../backend/app/schemas/supervisor.py#L99)
   `GoalContractSummary`** — renamed
   `weekly_hours_committed: float | None` →
   `weekly_hours: str | None`. Now matches the model + migrations'
   bucket-string semantics. `expires_at: datetime | None = None`
   stays as a forward-looking field (defaults None forever until a
   future migration adds the column — see "Recommended
   resolution" below).

2. **[`services/agentic_snapshot_service.py`](../../backend/app/services/agentic_snapshot_service.py#L211)
   `_load_goal_contract`** — rewrote the SQL to use the real
   columns (`SELECT weekly_hours, target_role FROM goal_contracts
   WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1`). Dropped
   the `expires_at` SELECT and the `WHERE expires_at` clause
   entirely. Removed the `float()` cast on `row[0]`. **Added
   `await db.rollback()` inside the except clause** so the asyncpg
   transaction recovers cleanly; the rollback itself is wrapped in
   its own try/except so a rollback failure never shadows the
   original error in observability — both errors get structured
   fields so logs can correlate them.

3. **[`docs/followups/goal-contracts-schema-divergence.md`](.)** —
   this file.

4. **[`tests/test_services/test_snapshot_service_rollback.py`](../../backend/tests/test_services/test_snapshot_service_rollback.py)** —
   pin both contracts:
   - The fixed real-column query parses against the actual schema
     (happy-empty + happy-row paths)
   - When ANY SQL inside `_load_goal_contract` fails (triggered via
     a synthetic `SELECT nonexistent_column ...` so the test stays
     durable across schema changes), a subsequent `agent_call_chain`
     INSERT on the same session **succeeds** — proves the rollback
     recovered the asyncpg state. Without the rollback fix, this
     INSERT raises `InFailedSQLTransactionError`.

The defensive fix is intentionally narrow: it eliminates the broken
behavior without trying to deliver the architecturally-intended
"goal contracts that can expire with a numeric weekly-hours
commitment" semantics. That work belongs to a deliberate future
deliverable — see below.

## Recommended long-term resolution (D12 work)

When **D12 ships the career bundle** (career_coach + study_planner
+ resume_reviewer + tailored_resume per Pass 3c E3-E6),
study_planner will need to formalize the
weekly-hours-committed concept (per [Pass 3c E4](../../docs/architecture/pass-3c-agent-migration-playbook.md)
which references `commit_plan` + `track_adherence` as
study_planner-specific tools). At that point:

1. Decide whether `weekly_hours` should remain a bucket string
   (matching the existing UX surface where students pick from
   `"3-5"`, `"6-10"`, `"11+"`) or become a numeric commitment with
   range-parsing semantics. Likely answer: keep the bucket as the
   user-facing input, add a derived numeric field if planner code
   needs to do arithmetic.
2. Decide whether `goal_contracts` should grow an `expires_at`
   column. The spec implies "yes" (active goal contracts have
   expiry windows), but no current product surface enforces or
   displays expiry. If yes, write a migration adding
   `expires_at TIMESTAMPTZ NULL` and update the snapshot service
   query to honor it (mirror the existing
   `course_entitlements.expires_at` pattern).
3. Update `GoalContractSummary` accordingly — either rename
   `weekly_hours` back to `weekly_hours_committed` with the new
   numeric semantics, or keep the rename and add a separate
   `weekly_hours_target_minutes` derived field.

The temporary fix above keeps the option open for any of these
shapes without committing to one prematurely.

## Why these gaps existed

- **Pass 3b §3.1 spec gap.** The architecture pass named
  `GoalContractSummary` and described its purpose with prose
  comments but didn't pin exact field names against the existing
  model. Architecture passes that touch existing schema should
  cite the model file + column types verbatim to prevent
  field-name divergence.
- **D9 implementation took the architecture comment as the schema
  definition.** D9 wrote new schema field names that matched the
  Pass 3b prose comment ("weekly hours, target role") rather than
  the model's actual column names. Field-name discipline wasn't
  enforced via cross-reference checks.
- **D9 smoke didn't exercise the failing path.** Either Redis cache
  hit, or no goal_contracts row for the test student, or
  fresh-session-per-call test pattern that hid the
  asyncpg transaction poisoning.

## Cross-references

- [Pass 3b §3.1](../architecture/pass-3b-supervisor-design.md) —
  architecture spec for `GoalContractSummary` (the gap that started
  this)
- [Pass 3c E4](../architecture/pass-3c-agent-migration-playbook.md) —
  study_planner specification (the proper future home for goal
  contract semantics)
- [models/goal_contract.py](../../backend/app/models/goal_contract.py) —
  the actual schema D9 should have matched
- [schemas/goal_contract.py](../../backend/app/schemas/goal_contract.py) —
  `WeeklyHours = Literal["3-5", "6-10", "11+"]`, the bucket-string
  convention used throughout the rest of the codebase
- [migrations 0002 / 0018 / 0025 / 0044](../../backend/alembic/versions/) —
  the actual migration history of `goal_contracts`
- [services/agentic_snapshot_service.py](../../backend/app/services/agentic_snapshot_service.py) —
  the patched function with the rollback contract
- [tests/test_services/test_snapshot_service_rollback.py](../../backend/tests/test_services/test_snapshot_service_rollback.py) —
  the pin-the-contract regression test
