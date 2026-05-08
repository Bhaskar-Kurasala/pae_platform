# BUG-CP1D — interview_sessions.updated_at NOT NULL violation

**Status:** Open. **Severity: LAUNCH-BLOCKER candidate** (if production
schema matches `playwright_test`).
**Origin:** D18 Phase B CP1 journey (d) authoring, 2026-05-09.
**Surfaced by:** test_cp1_journey_d_mock_interview.py
(@pytest.mark.xfail strict=True, Convention A).

## What this is

POST `/api/v1/mock/sessions/start` raises 500 with
`asyncpg.exceptions.NotNullViolationError: null value in column
"updated_at" of relation "interview_sessions" violates not-null
constraint`. The entire mock-interview start path is broken on the
`playwright_test` database.

## Pattern 22 schema-vs-model drift

  * **Live schema** (`playwright_test`):
    `updated_at timestamp with time zone NOT NULL DEFAULT now()`.
  * **ORM model** (`backend/app/models/interview_session.py:55`):
    `updated_at: Mapped[datetime | None] = mapped_column(...,
    nullable=True)` — **no `server_default`**.
  * **Service** (`backend/app/services/mock_interview_service.py:302`):
    creates `InterviewSession(...)` without setting `updated_at`,
    then `db.flush()`.

Because the model declares `nullable=True` and the field is unset,
SQLAlchemy generates an INSERT that explicitly supplies `NULL` for
`updated_at` (overriding the DB-side `DEFAULT now()`). Postgres
rejects on the NOT NULL constraint.

## Why the dev DB doesn't show the bug

The dev `platform` database has `updated_at` nullable (older migration
state). The migration that added `NOT NULL` ran against
`playwright_test_template` but `platform` was never migrated forward
on this column. So:

  * Dev work + manual smoke against `platform` → bug invisible.
  * Phase B journey (d) on `playwright_test` → bug fires every call.
  * Production: depends on which schema is deployed. **If production
    has the NOT NULL constraint, the entire mock interview flow is
    broken in prod today.**

## Fix scope

Two viable fixes:

**Option α — Add `server_default=sa.func.now()` to the ORM model.**
SQLAlchemy then omits `updated_at` from the INSERT, letting Postgres
apply the default.

```python
updated_at: Mapped[datetime] = mapped_column(
    sa.DateTime(timezone=True),
    server_default=sa.func.now(),
    onupdate=sa.func.now(),
    nullable=False,
)
```

**Option β — Service sets `updated_at` explicitly on create.**

```python
session = InterviewSession(
    ...,
    updated_at=datetime.now(UTC),
)
```

Option α is the canonical fix (matches the schema; doesn't require
service awareness).

## Verification when fix lands

1. Drop `@pytest.mark.xfail` from
   `test_cp1_journey_d_mock_interview.py::test_mock_interview_session_starts_and_accepts_one_answer`.
2. Re-run under runner overlay; expect PASS in 30-60s with real LLM cost.
3. Verify dev `platform` DB also has the NOT NULL migration applied
   (otherwise this drift recurs the next time a fresh DB is provisioned).

## Cross-references

  * `backend/tests/playwright/journeys/test_cp1_journey_d_mock_interview.py` — the xfailed test.
  * `backend/app/models/interview_session.py:55` — the ORM model.
  * `backend/app/services/mock_interview_service.py:302` — the service flush.
  * Pattern 22 evidence base — schema-vs-model drift instance.
