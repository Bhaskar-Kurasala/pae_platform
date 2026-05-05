# SQLite test backend compatibility — residual gaps

## Status

- **JSONB DDL gap: RESOLVED in D10 Checkpoint 1** (commit `<hash>` — to be filled
  at commit time) via `@compiles(JSONB, "sqlite")` shim in
  `tests/conftest.py`. Result: **618 pre-existing fixture-setup
  errors → 0 JSONB-attributable errors**, +580 tests now run for the
  first time.
- **44 residual failures newly visible** — pre-existing test bitrot
  the JSONB error was masking. Classified below; deferred to D17
  cleanup.
- **ARRAY parameter binding gap: STILL OPEN** — accounts for ~18
  of the 44 residual failures. See
  [test_notebook_idempotent.py:5](../../backend/tests/test_routes/test_notebook_idempotent.py#L5)
  for a representative repro.

## What was fixed

The six D1 agentic-OS primitive models declare `postgresql.JSONB` columns:

- `agent_call_chain.payload`, `agent_call_chain.result`
- `agent_escalation.best_attempt`
- `agent_memory.value`
- `agent_proactive_run.payload`
- `agent_tool_call.args`, `agent_tool_call.result`
- `student_inbox.metadata_`

Tests using SQLite fixtures (the default `db_session` /  `client` fixture
in `tests/conftest.py`) previously crashed at `Base.metadata.create_all`
with:

```
sqlalchemy.exc.CompileError: (in table 'agent_call_chain', column 'payload'):
Compiler <sqlalchemy.dialects.sqlite.base.SQLiteTypeCompiler ...>
can't render element of type JSONB
```

That error fired at fixture-setup time on ~600 individual test cases —
every test in any file that used the `client` or `db_session` fixture
and exercised the full `Base.metadata` path.

**The fix:** `tests/conftest.py` now registers
`@compiles(JSONB, "sqlite")` returning `"TEXT"`, alongside the
pre-existing `@compiles(ARRAY, "sqlite")` shim. The Postgres render path
is untouched (`JSONB` still renders as `JSONB` against the Postgres
dialect — pinned by the regression test described below).

**Why TEXT and not JSON:** Concern C investigation (D10 Checkpoint 1)
confirmed zero JSONB operators in app code (no `->>`, `->`, `@>`,
`jsonb_*`, `.astext`, `.op('->>')` patterns); every JSONB column is
treated as an opaque whole-blob — written as a dict, read as a dict,
mutated in Python, written back. TEXT is the more portable choice and
works on every SQLite version without depending on the JSON1 extension.
Switch to JSON if a future query needs `json_extract`.

**Server defaults — the surprise the pin test caught:**
`student_inbox.metadata_` originally used `func.cast("{}", JSONB)`
as its `server_default`. The investigation report predicted this
would cooperate with the shim automatically; the pin test
([test_jsonb_default_cast_works_on_sqlite](../../backend/tests/test_infra/test_sqlite_jsonb_compat.py))
caught that it doesn't:

```
sqlalchemy.exc.CompileError: (in table 'student_inbox', column 'metadata'):
No literal value renderer is available for literal value "'{}'" with datatype JSONB
```

`@compiles(JSONB, "sqlite")` registers a column-DDL renderer
(`visit_JSONB`), but `func.cast(<literal>, JSONB)` needs a separate
literal-value renderer for the JSONB target type at cast-emit time.

**Resolution (one-line model change in this same commit):** swapped
`server_default=func.cast("{}", JSONB)` → `server_default=sa_text("'{}'")`.
Postgres still infers JSONB at INSERT time (text `'{}'` auto-casts
to the JSONB column given the column type); SQLite renders the
default as a plain TEXT literal. Production migration (0054) keeps
its existing `sa.text("'{}'::jsonb")` — Postgres deployment
behavior unchanged. The original concern about raw `'{}'::jsonb`
text strings in models turned out to be a partial false alarm
(no such strings exist in models); the actual gap was the cast
literal-renderer above. The only `::jsonb` literals anywhere are
inside production runtime SQL in `entitlement_service.py`, which
only executes against real Postgres.

**Regression-pin test:**
[tests/test_infra/test_sqlite_jsonb_compat.py](../../backend/tests/test_infra/test_sqlite_jsonb_compat.py).
Five assertions:

1. `JSONB().compile(dialect=sqlite_dialect())` returns `"TEXT"` (the shim)
2. `JSONB().compile(dialect=pg_dialect())` returns `"JSONB"` (no production regression)
3. `Base.metadata.create_all` succeeds on SQLite and produces all six JSONB-bearing tables
4. End-to-end dict round-trip through `student_inbox.metadata_` (the trickiest server_default path)
5. Postgres-side guard (auto-skipped when no reachable Postgres at `TEST_PG_DSN`)

**Result (measured against post-D10-Checkpoint-1 baseline of
1149 pass / 0 fail / 5 skip / 618 errors):**

| Metric | Before JSONB fix | After JSONB fix | Delta |
|---|---|---|---|
| Pass | 1149 | **1729** | **+580** |
| Fail | 0 | **44** | **+44** ⚠ residual surface, not regressions — see below |
| Skip | 5 | 5 | 0 |
| Errors | 618 | **0** | **−618** ✓ |

The +44 are pre-existing test bitrot the JSONB error was masking,
not regressions caused by the shim. They are documented and triaged
in "What's still open" below.

## What's still open

The shim cleared 618 errors. The full regression now reports
**44 residual failures** that the JSONB error was previously
masking. None are caused by the shim — they are pre-existing test
bitrot that pytest can finally *attempt to run*, then fail for
reasons unrelated to JSONB.

Classified breakdown (D10 Checkpoint 1 sample):

### NotebookEntry ARRAY parameter binding (~18 of 44)

- **Affected files:** `tests/test_notebook.py` (4),
  `tests/test_notebook_summarize.py` (1),
  `tests/test_routes/test_notebook_summary_route.py` (2),
  `tests/test_services/test_notebook_service.py` (9),
  `tests/test_services/test_srs_graduates_notebook.py` (2)
- **Symptom:** `sqlalchemy.exc.ProgrammingError` (truncated as
  `sqlalchemy.exc.Pr...` in `-q` mode) when binding the
  `notebook_entries.tags` ARRAY column at INSERT time —
  `sqlite3.ProgrammingError: type 'list' is not supported`.
- **Repro:** [test_notebook_idempotent.py:5](../../backend/tests/test_routes/test_notebook_idempotent.py#L5)
  has the most explicit description.
- **Hint for the next contributor:** this is a runtime issue, not a
  DDL issue. The `@compiles(ARRAY, "sqlite")` shim handles DDL
  rendering (CREATE TABLE) but doesn't translate Python `list` values
  to SQLite-acceptable bindings at INSERT/UPDATE time. A fix probably
  needs either a parameter-binding processor, a custom TypeDecorator,
  or migrating the affected models (`notebook_entries.tags`) to a
  cross-backend type (`sa.JSON` would work; `Text` with comma-join
  would too).

### Test bitrot — production code drift (~10-15 of 44)

Tests that patch attributes that no longer exist on the production
modules they target. Sampled:

- `tests/test_api/test_career.py` (4 failures): every test patches
  `app.services.career_service.AsyncAnthropic`, which the production
  code no longer exposes. **Fix is in the test file** — update the
  patch target, or use `mock.patch.object` against a real attribute.
- `tests/test_api/test_chat_quiz.py` (2): similar shape, likely the
  same pattern (LLM-client refactor without test updates).
- `tests/test_api/test_chat_edit.py`, `test_progress.py`,
  `test_lessons.py`, `test_enrollment.py`, `test_goals.py`: assertion
  mismatches (`assert 200 == 404`, `assert 401`) suggesting
  auth/route refactors not reflected in tests.

### Service-layer assertion drift (~10 of 44)

- `tests/test_services/test_learning_session_service.py` (9 failures):
  every test in the file fails. Likely a single shared fixture or
  helper drifted; one focused look will probably fix all 9 at once.
- `tests/test_services/test_growth_snapshot_service.py` (1),
  `test_progress_service_weighted.py` (1), `test_quota_service.py` (1):
  assorted assertion drift.

### Why the shim doesn't fix these

These tests were never running successfully against SQLite. The JSONB
error fired at fixture setup — every test in an affected file errored
out before its body could run. With the shim in place, fixture setup
succeeds, the test body runs, and the underlying drift becomes
visible. The shim gives us **honest measurement**, not regressions.

### Recommendation

These 44 belong in their own remediation deliverable (D17 cleanup is
the natural home, per the Pass 3j scope). Triage is straightforward
with the breakdown above:

1. **NotebookEntry ARRAY binding (18)** — one focused fix; either
   migrate `notebook_entries.tags` to `sa.JSON` or write a
   TypeDecorator. Estimate: 1–2 hours.
2. **Test bitrot — patch targets (~10)** — update each test's
   `mock.patch` target string. Estimate: 30 minutes per file.
3. **Service-layer drift (~10)** — investigate per-file; many will
   share a root cause. Estimate: 1–3 hours total.

Total residual cleanup: ~5–8 hours of focused work, well outside
D10's scope.

## Why these gaps existed

- The agentic-OS primitive models (D1) were written as Postgres-from-
  day-one infrastructure. JSONB columns were chosen for the
  flexibility they give in production (vector indexes, GIN indexes,
  JSON path operators if needed later).
- Earlier contributors hit similar SQLite-vs-Postgres traps and chose
  `sa.JSON` for new models — see
  [chat_feedback.py:8](../../backend/app/models/chat_feedback.py#L8)
  and
  [saved_skill_path.py:18](../../backend/app/models/saved_skill_path.py#L18)
  with explicit "works with SQLite in tests" comments.
- The D1 models would lose Postgres JSONB capabilities (e.g. GIN
  indexing on the `value` column for fast key lookups, JSON path
  operators in the curriculum graph queries Pass 3e plans for) if
  retroactively migrated to `sa.JSON`. The shim approach preserves
  both production capability and test compatibility.

## Sibling pattern: silent skips when TEST_PG_DSN unset (registered 2026-05-05)

Tool tests requiring real Postgres skip silently when `TEST_PG_DSN`
isn't set. The default
(`postgresql+asyncpg://postgres:postgres@localhost:5433/platform`)
doesn't reach `db:5432` from inside the container; the in-container
DSN must be set explicitly:
`TEST_PG_DSN=postgresql+asyncpg://postgres:postgres@db:5432/platform`.

Surfaced during D11 Checkpoint 1 — the new `senior_engineer` tool
tests skipped silently in regressions until the env override was
applied. Same constraint affects:

- `tests/test_agents/tools/agent_specific/billing_support/*`
- `tests/test_agents/tools/agent_specific/senior_engineer/*` (D11)
- `tests/test_agents/primitives/test_memory.py` (uses the same fixture)
- any future tool tests using the `pg_session` per-schema fixture

Silent skips are a class of test infrastructure bug — tests that
should be verifying behavior look identical in CI to tests that
don't apply. Auto-detect would be cleaner UX: if running inside a
container with a reachable `db:5432`, prefer that over the
host-side default; emit an explicit "skipped because no Postgres"
message rather than the silent `pytest.skip`.

**Triage:** D17 (test infrastructure cleanup) unless 30 minutes can
be spared during a future deliverable touching the conftest.

## Cross-references

- `tests/conftest.py` — the shim itself, with the long-form rationale
  in the comment block alongside
- `tests/test_infra/test_sqlite_jsonb_compat.py` — pin-the-shim regression test
- `docs/lessons.md` (2026-04-08 entry) — historical guidance to
  prefer `sa.JSON` over `JSONB` in models for SQLite compat
- `frontend/e2e/agentic-foundation.spec.ts` — the production-shape
  Playwright test path (kept around because it exercises real Postgres
  end-to-end; complements the unit tests, doesn't replace them)
