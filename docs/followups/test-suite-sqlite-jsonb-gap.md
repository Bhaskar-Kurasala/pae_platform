# Test suite — SQLite + JSONB pre-existing gap

**Status:** Open — pre-existing baseline issue, surfaced (not introduced)
by D9.
**Created:** 2026-05-03 (D9 Checkpoint 4).
**Blocked by:** nothing — small refactor.

## The gap

The unit-test suite uses an in-memory SQLite database
(`tests/conftest.py`'s `db_session` fixture). Six models declare
columns as `postgresql.JSONB`:

- `app/models/agent_call_chain.py`
- `app/models/agent_escalation.py`
- `app/models/agent_memory.py`
- `app/models/agent_proactive_run.py`
- `app/models/agent_tool_call.py`
- `app/models/student_inbox.py` (uses `'{}'::jsonb` server_default)

SQLite cannot render JSONB columns OR JSONB literal casts in
server_default values. `Base.metadata.create_all` crashes at
container startup of any test that uses the `client` fixture.

## Pre-existing breakage

This is NOT a D9 regression. Before D9 shipped:

- `tests/test_routes/test_admin_audit.py` (4 tests) — already fails
  with the same JSONB compile error.
- Any other route test that imports `app.main` and runs against the
  in-memory SQLite — fails identically.

D9 surfaced the issue because the new agentic route imports trigger
the same model-loading path. The new D9 HTTP tests
(`tests/test_routes/test_agentic_endpoint.py`) were drafted, attempted,
hit the same wall, and **deleted** during D9 Checkpoint 4 sign-off.
HTTP-level coverage of the agentic endpoint is provided by the
Playwright E2E suite at `frontend/e2e/agentic-foundation.spec.ts`,
which runs against the real Postgres-backed container.

## Why a partial shim isn't enough

A `@compiles(JSONB, "sqlite")` shim in `tests/conftest.py` handles
the column type but NOT server_default expressions like
`server_default=sa.text("'{}'::jsonb")`. The `student_inbox` model
hits this exact second wall.

A complete fix needs:

1. `@compiles(JSONB, "sqlite")` returning `"JSON"` — the column shim.
2. Either:
   (a) Replace every `'{}'::jsonb` server_default with `'{}'` in the
       model files (Postgres still accepts it; SQLite renders it
       cleanly), OR
   (b) Override server_default at create_all time via a SQLAlchemy
       event listener that strips the `::jsonb` cast for SQLite.

Option (a) is one-line-per-model + a regression test. Option (b) is
slicker but more magical.

## Recommendation

Apply option (a) in a focused PR:

```python
# Before
sa.Column(
    "metadata",
    JSONB,
    nullable=False,
    server_default=sa.text("'{}'::jsonb"),
)

# After
sa.Column(
    "metadata",
    JSONB,
    nullable=False,
    server_default=sa.text("'{}'"),  # Postgres infers JSONB from column type
)
```

Then add the `@compiles(JSONB, "sqlite")` shim to `tests/conftest.py`.

Verification: `tests/test_routes/test_admin_audit.py` (which was
already broken before D9) starts passing. That's the canary for "the
HTTP test path is unblocked."

## Scope

Out of D9 scope. D9's HTTP-level coverage is the Playwright E2E
spec; unit-level HTTP tests for the agentic endpoint join the
queue when this gap is closed.

## Cross-references

- `tests/conftest.py` — note about the gap + the existing `@compiles(ARRAY, "sqlite")` precedent
- `docs/lessons.md` (2026-04-08 entry) — historical guidance to
  prefer `sa.JSON` over `JSONB` in models for this exact reason; the
  Agentic OS primitive models predate the lesson
- `frontend/e2e/agentic-foundation.spec.ts` — the production-shape
  test path that covers the agentic endpoint end-to-end while this
  gap remains
- `tests/test_agents/test_checkpoint4_routing.py` — Layer 1 + Layer 2
  routing tests that exercise the Supervisor without HTTP

## Tag

**Non-blocking; pre-existing baseline.** D9 ships green via routing
tests + Playwright E2E. Closing this gap unblocks the wider HTTP
test pattern, useful for D10+ as more agents migrate.
