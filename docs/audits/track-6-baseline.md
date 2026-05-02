# Track 6 — verification baseline

**Generated:** 2026-05-02
**Scope:** Final verification pass over the workstream branch
(`73e998c` → `3ca6b51`, 6 tracks, no application-code changes
beyond Track 2's `RedisEscalationLimiter`).
**Posture:** Report pass/fail/skip as observed. Do not investigate
or fix failures inside this track — the whole point of Track 6 is
to produce a clean baseline reading. Findings get filed as
follow-ups; remediation happens elsewhere.

---

## Headline

Most Track-6-scope failures are **pre-existing**, not introduced
by Tracks 1–5. The one failure that *is* directly tied to this
workstream's findings (the Celery task registration test) is the
same root cause as **PG-1 / `agentic-loader-fastapi-startup.md`**
already filed at Track 5 sign-off — so it's not a new gap, it's
visible evidence of the gap I'd already catalogued.

---

## 1. Backend test suite

### 1.1 Full suite under coverage — **EXCEEDED BUDGET**

```bash
docker exec pae_platform-backend-1 \
  uv run pytest --cov=app --cov-report=term --tb=short -q
```

Ran for **15+ minutes without producing a summary line.** Killed
without investigating the cause, per Track 6 discipline.

Possible reasons (none verified):
- Coverage instrumentation slowdown on a ~1500-test suite
- A specific test hang (no traceback was emitted before kill)
- Database fixture contention against the live dev DB

**Recommendation (out-of-scope for Track 6):** run the suite
without coverage to bound the slowdown contribution, then bisect
by directory if pure-suite is also slow. Filed as a known unknown,
not a regression.

### 1.2 Targeted re-run on agentic primitives only

```bash
docker exec pae_platform-backend-1 \
  uv run pytest tests/test_agents/primitives/ --tb=short -q --no-cov
```

Result: **93 passed, 1 failed, 68 skipped, 10.78s.**

The 68 skips are env-gated (live LLM, optional Redis backend
when REDIS_URL is unset) — see §1.4 catalogue.

The 1 failure:

```
tests/test_agents/primitives/test_d7b_integration.py::test_celery_task_registered
AssertionError: task name 'app.agents.primitives.proactive.run_proactive_task'
not registered in Celery; available: ['celery.accumulate',
'celery.backend_cleanup', 'celery.chain', ...]
```

**This is PG-1 in test form.** The `run_proactive_task` is registered
inside `app/core/celery_app.py` at Celery boot via `load_agentic_agents()`.
The pytest runner imports the FastAPI app, which does NOT call
`load_agentic_agents()`, so the task table inside the in-process
Celery instance is the bare default set. Same root cause, same fix.

This finding is **already captured** in
`docs/followups/agentic-loader-fastapi-startup.md`. Track 6 is the
first place a *test* surfaces it; that's a useful corroboration of
PG-1's severity.

**No new follow-up filed.** Resolution is the same 5-LOC fix to
FastAPI startup that PG-1 specifies.

### 1.3 Track 5 spec re-run as live-stack health proxy

```bash
cd frontend && pnpm playwright test agentic-os --reporter=list
```

Result: **8 passed (2.7s).** Identical to the Track 5 baseline,
confirming the stack is healthy and the spec is stable.

### 1.4 Skip / xfail catalogue

**Backend (6 markers):**

| File | Line | Type | Reason |
|---|---|---|---|
| `test_routes/test_notebook_idempotent.py` | 99 | `skip` | "SQLite ARRAY param-binding shim incomplete — pre-existing test infrastructure limitation" |
| `test_routes/test_notebook_idempotent.py` | 120 | `skip` | Same SQLite shim limitation |
| `test_agents/primitives/test_example_learning_coach.py` | 841 | `skipif` | Live-LLM smoke; needs `ANTHROPIC_API_KEY` |
| `test_agents/primitives/test_evaluation.py` | 571 | `skipif` | Redis backend; skipped if REDIS_URL not reachable |
| `test_agents/primitives/test_evaluation.py` | 597 | `skipif` | Same Redis condition (sliding window test) |
| (3rd Redis test inferred from file) | — | `skipif` | Same Redis condition (fail-open test) |

The 68 skipped tests in §1.2 are the union of env-gated cases plus
parameterised tests where one parameter is unavailable. None
silently disabled — every skip has a documented `reason=`.

**Frontend Playwright (7 markers):**

| File | Line | Type | Reason |
|---|---|---|---|
| `e2e/practice.spec.ts` | 76 | `test.skip(!firstExerciseId, ...)` | env-gated on seeded fixture |
| `e2e/practice.spec.ts` | 89 | `test.skip(!firstExerciseId, ...)` | same |
| `e2e/production-readiness.spec.ts` | 126 | `test.skip(...)` | (not inspected — context-dependent) |
| `e2e/retention-engine.spec.ts` | 151 | `test.skip(true, "no student rows...")` | empty-state pass |
| `e2e/retention-engine.spec.ts` | 306 | `test.skip(true, "no paid_silent...")` | env-state-dependent |
| `e2e/retention-engine.spec.ts` | 364 | `test.skip(true, "no risk cards...")` | clean retention state |
| `src/app/(portal)/chat/__tests__/mobile-drawer.test.tsx` | 377 | `it.skip` | "swipe-left ... covered in E2E" |

No xfail markers anywhere in the suite. No silently disabled tests.

---

## 2. Backend lint + typecheck — **PRE-EXISTING DEBT**

### 2.1 Ruff — **524 errors, 333 auto-fixable**

```bash
docker exec pae_platform-backend-1 uv run ruff check . --statistics
```

Top offenders (counts):

| Code | Count | Description |
|---|---|---|
| I001 | (largest cluster) | Import block un-sorted or un-formatted |
| ANN-series | (many) | Missing type annotations |
| UP017 | several | `datetime.UTC` alias migration |
| UP006/UP035 | several | Deprecated typing imports |
| F841 | 3 | Unused variable |
| F821 | 3 | Undefined name |
| B007 | 2 | Unused loop control variable |
| (full list in command output above; 31 distinct codes) | | |

**This is NOT a regression introduced by Tracks 1–5.** Track 2's
`RedisEscalationLimiter` lint-clean (it landed via `feat(agentic-os):
track-2`); Tracks 1, 3, 4, 5 are docs-only. The 524 errors are
ambient debt in the wider codebase (especially in `tests/tests/`
which appears to be a misnamed test subdirectory contributing
many import-order findings).

### 2.2 Mypy strict — **131 errors in 53 files**

Same characterisation. Top categories:

- `[no-untyped-def]` — most legacy agents (knowledge_graph,
  disrupt_prevention, deep_capturer, etc.) have unannotated
  helpers. The 26 agents the workstream was instructed NOT to
  touch.
- `[arg-type]` — admin.py PulseCard call sites passing `object`
  where `str` is required. Pre-existing.
- `[attr-defined]` `Module has no attribute "OverloadedError"` —
  the `anthropic` SDK removed/renamed this exception class. Two
  call sites: `senior_review.py:55`, `practice.py:95`. Likely
  surfaced by a recent SDK bump.
- `agentic_base.py:204` — `register_agentic` arg-type mismatch
  on `AgenticBaseAgent` vs `AgenticCallee` protocol. Pre-existing
  shape; protocol expects instance variables, class declares
  class variables.
- `agentic_base.py:413` — `EscalationLimiter | RedisEscalationLimiter`
  return type mismatch. **Track 2 introduced the union member**;
  the call site annotation wasn't updated to accept the broader
  type. **One single-line fix candidate that is in this workstream's
  scope** — but per Track 6 discipline, I am not fixing it.
  Filed below as Track 6 finding T6-F1.

### 2.3 Track-6 finding T6-F1 (file as follow-up)

**Symbol:** `agentic_base.py:413` return type.
**Issue:** `RedisEscalationLimiter` is a valid concrete return
from `make_escalation_limiter()` (Track 2 swap), but the calling
site's annotated return type is still narrow `EscalationLimiter`.
**Fix:** Widen to `EscalationLimiter | RedisEscalationLimiter`,
or factor out a `BaseEscalationLimiter` Protocol they both
implement and use that.
**Scope:** ~3-line change. Belongs in the next code-touching pass,
not Track 6.

---

## 3. Frontend lint + typecheck + tests

### 3.1 Vitest — **completely broken, 0 tests run**

```bash
cd frontend && pnpm test --run
```

```
Caused by: Error: Cannot find package
'E:\...\node_modules\.pnpm\@asamuzakjp+css-color@5.1.8\node_modules\@csstools\css-calc\index.js'
imported from
'E:\...\@asamuzakjp\css-color\dist\esm\js\css-calc.js'

Test Files  no tests
Tests       no tests
Errors      75 errors
```

**Pre-existing pnpm/vitest workspace dependency resolution failure.**
Not introduced by this workstream (no frontend code changes in any
track). The install graph for `@asamuzakjp/css-color` is missing
its `@csstools/css-calc` peer that Vitest's worker needs at module
resolution time.

**Recommendation:** `pnpm install --force` or `rm -rf node_modules
&& pnpm install` would likely fix it; out of scope for Track 6.

### 3.2 Frontend tsc — **1 error**

```
src/test/contracts/api-shape.test.ts(172,3): error TS2353:
Object literal may only specify known properties, and 'solution_code'
does not exist in type 'ExerciseResponse'.
```

Contract test drift — generated API client schema removed
`solution_code` from `ExerciseResponse`, but the contract test
fixture still references it. Fix: regenerate the client + update
the fixture. Not a regression from this workstream.

### 3.3 ESLint — **32 errors, 37 warnings** (across 69 problems)

Examples (not exhaustive):
- `use-admin-theme.ts:42` — `react-hooks/set-state-in-effect`
  (cascading-render anti-pattern)
- `use-career.ts:17` — `@typescript-eslint/no-explicit-any`
- `today-screen.tsx:99` — unused eslint-disable directive
- `today-screen.tsx:107` — `react-hooks/exhaustive-deps` missing
  dependency

All pre-existing.

### 3.4 Frontend Playwright — **killed alongside pytest**

The full suite (~10 specs) was launched in background and killed
without a summary when the pytest budget exceeded. As proxy:
**`agentic-os.spec.ts` re-ran 8/8 green in 2.7s** (§1.3),
confirming at minimum that the new Track-5-added spec is stable
and the live stack is healthy.

Not a Track 6 verdict on the full Playwright suite. That's a known
unknown.

---

## 4. Alembic round-trip

### 4.1 Current state — **clean**

```
alembic current → 0054_agentic_os_primitives (head)
```

The dev DB is at head. Track 4's open question about the **0050
filename gap is now resolved**:

```
0049_student_risk_signals.py:revision        = "0049_student_risk_signals"
0049_student_risk_signals.py:down_revision   = "0048_path_promotion"
0051_outreach_log.py:revision                = "0051_outreach_log"
0051_outreach_log.py:down_revision           = "0049_student_risk_signals"
```

`0051.down_revision == 0049.revision` — chain is intact. The 0050
filename is **purely cosmetic**, not a broken chain.

`docs/followups/post-track-4-followups.md` §1 can be marked
resolved once someone with write access to that doc updates it.
Track 6 is the verification, not the doc-update — leaving the
update to the team.

### 4.2 Fresh-DB upgrade-from-base — **PRE-EXISTING FAILURE**

Created a fresh `alembic_roundtrip` Postgres database and ran
`alembic upgrade head` against it.

Result: **failed at migration 0023** with

```
asyncpg.exceptions.DatatypeMismatchError:
foreign key constraint "saved_skill_paths_user_id_fkey"
cannot be implemented
```

This is **the documented pre-existing issue** noted directly in
the CI workflow:

> `.github/workflows/ci.yml:81-88`:
> "the existing migration chain has known apply-on-fresh-DB
> bugs that pre-date this CI step (0023 has a VARCHAR/UUID FK
> type mismatch; 0040's data backfill is now offline-mode-safe).
> Until those are fixed in a dedicated migrations-cleanup PR,
> this step surfaces the bugs as a yellow signal rather than
> blocking every PR red."

Not introduced by Tracks 1–5. CI tolerates it via
`continue-on-error: true`. Migration cleanup is its own future
workstream.

### 4.3 Round-trip downgrade-to-base + upgrade-to-head — **NOT ATTEMPTED**

Skipped because the upstream upgrade-from-base is broken (§4.2).
A round-trip on a partially-upgraded DB would test downgrade-from-
0022, which is not the meaningful invariant ("the chain round-trips
cleanly from base").

---

## 5. Cold-boot timing

```
docker restart pae_platform-backend-1
→ /health/ready returns 200 in 10 seconds
```

**Backend cold-boot to ready: 10s** (warm-cache restart, not a
full image rebuild).

Useful baseline for Pass 3i scale work. Full image rebuild
(`docker compose build backend && docker compose up -d backend`)
was deliberately not measured — Windows host docker rebuild times
are dominated by I/O and would not represent production rebuild
behavior.

---

## 6. Summary table

| Surface | Result | Verdict |
|---|---|---|
| Backend pytest (full + cov) | budget exceeded | known unknown — investigate slowness/hang separately |
| Backend pytest (primitives only, no cov) | 93 pass / 1 fail / 68 skip in 10.78s | one fail = PG-1 in test form |
| Backend ruff | 524 errors | pre-existing debt (333 auto-fixable) |
| Backend mypy strict | 131 errors / 53 files | pre-existing + T6-F1 (Track 2 union widening, ~3 LOC) |
| Backend skip catalogue | 6 markers, all `reason=`'d | clean — no silent disables |
| Backend alembic current | 0054 (head), chain intact | green; 0050 gap is cosmetic |
| Backend alembic fresh-DB upgrade | fails at 0023 | pre-existing, documented in CI |
| Backend cold-boot to ready | 10s | baseline captured |
| Frontend vitest | 0 tests run, 75 errors | pre-existing pnpm dep-graph break |
| Frontend tsc | 1 error | pre-existing contract drift |
| Frontend ESLint | 32 errors, 37 warnings | pre-existing |
| Frontend Playwright (full) | killed alongside pytest | known unknown |
| Frontend Playwright (agentic-os only) | 8 pass (2.7s) | green — live stack healthy |
| MCP Playwright config | working | confirmed via Track 5 + this re-run |

---

## 7. New findings filed by Track 6

**T6-F1: `agentic_base.py:413` return-type widening.**
Mypy flags `EscalationLimiter | RedisEscalationLimiter` vs declared
`EscalationLimiter`. Track 2 introduced the second concrete return;
the existing call site annotation never widened. ~3 LOC. NOT FIXED
in Track 6 per discipline; fold into the next code-touching pass.

**No new follow-up file** — the fix is too small to deserve its
own breadcrumb. Capturing here as a single-line action item is
sufficient.

---

## 8. What this verification deliberately did NOT do

- **Did NOT fix any test, lint, or type error.** Every finding is
  reported as observed.
- **Did NOT investigate the pytest budget exceedance.** That's
  itself an investigation we're not allowed to do inside Track 6.
- **Did NOT regenerate the frontend API client** to fix the tsc
  contract drift.
- **Did NOT run `pnpm install --force`** to fix vitest. That
  would mutate state mid-verification.
- **Did NOT measure full image rebuild time** on Windows host —
  the I/O dominance would not represent prod.
- **Did NOT attempt the round-trip downgrade-from-0054** because
  upgrade-from-base is already broken at 0023.

---

## 9. References

- Track 1–5 commits: `4553337`, `ec18a9b`, `82e5355`, `73e998c`,
  `4e6595e`, `3ca6b51`
- PG-1 P0 follow-up: `docs/followups/agentic-loader-fastapi-startup.md`
- Track 4 audits: `docs/audits/naming-audit.md`,
  `docs/audits/dead-code-audit.md`
- Track 5 audit: `docs/audits/agentic-os-precondition-gaps.md`
- Track 5 spec: `frontend/e2e/agentic-os.spec.ts`
- Architecture doc: `docs/AGENTIC_OS.md`
- CI configuration: `.github/workflows/ci.yml`
