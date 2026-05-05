# asyncpg rollback discipline — class-level pattern

**Status:** Open — D17 cleanup audit territory.
**Created:** 2026-05-03 (D10 Checkpoint 2 sign-off, after the
goal_contracts schema divergence fix surfaced two instances of
the same pattern).

## The pattern

Any function that catches database exceptions inside an active
asyncpg transaction MUST also call `await session.rollback()` to
recover the transaction state. Without rollback, downstream
statements on the same session fail with
`InFailedSQLTransactionError` (asyncpg-level) or
`PendingRollbackError` (SQLAlchemy-level), often manifesting as
confusing `specialist_error` / generic dispatch failures **far
from the original failure site**.

## Why this is subtle

asyncpg marks the transaction as failed at the protocol level the
moment any statement errors. The Python-level `try/except` catches
the exception and the function returns cleanly — **but the
transaction state is now poisoned**. The next statement on the
same session raises a confusing error that names the *new*
statement, not the original failure that caused the poisoning.
The catch was masking the bug within one function while the
cascade broke a caller several layers up.

The standard "fail-soft" pattern (`try/except Exception: log; return
None`) is necessary but not sufficient. It must include a rollback.

## The correct shape

```python
try:
    result = await db.execute(some_statement)
    # ... process result ...
    return value
except Exception as exc:  # noqa: BLE001
    log.warning(
        "context.operation.failed",
        error=str(exc),
        # ... structured fields ...
    )
    # Recover the asyncpg transaction so downstream statements
    # on this session don't trip InFailedSQLTransactionError /
    # PendingRollbackError.
    try:
        await db.rollback()
    except Exception as rollback_exc:  # noqa: BLE001
        log.error(
            "context.operation.rollback_failed",
            original_error=str(exc),
            rollback_error=str(rollback_exc),
            # ... structured fields ...
        )
    return None  # or whatever the fail-soft contract is
```

Two things matter:

1. **Always call `await session.rollback()`** in the except clause,
   even if the catch is "fail-soft and expected".
2. **Wrap the rollback itself in try/except.** A rollback failure
   should never shadow the original error in observability — both
   errors get structured fields with `original_error` as
   connective tissue so logs can correlate them.

## Known instances fixed during D10 Checkpoint 2

Both fixed in commit `21ff4f6`:

- [`agentic_snapshot_service._load_goal_contract`](../../backend/app/services/agentic_snapshot_service.py#L211)
  — was catching `UndefinedColumnError` from a schema-mismatch
  query, returning None, but leaving the transaction poisoned.
  See [goal-contracts-schema-divergence.md](./goal-contracts-schema-divergence.md)
  for the full story.
- [`billing_support_v2._record_interaction`](../../backend/app/agents/billing_support.py)
  call site (the wrapping try/except in `BillingSupportAgent.run`)
  — was catching `ForeignKeyViolationError` from a memory write,
  returning the answer payload, but leaving the transaction
  poisoned for the downstream `agent_call_chain` INSERT inside
  `call_agent`.

Pin tests live at
[tests/test_services/test_snapshot_service_rollback.py](../../backend/tests/test_services/test_snapshot_service_rollback.py).
The "synthetic always-failing query" pattern in test #3 is the
canonical way to pin this contract for any function that catches
DB exceptions; copy that shape when adding new such functions.

## Other instances likely exist

This is a class-level pattern. The two D10 instances were
discovered via end-to-end smoke verification — the kind of test
that exercises a full orchestrator path on a single session.
Other instances likely exist throughout the codebase, particularly
in:

- Service-layer functions that catch DB exceptions for "best
  effort" writes (audit logs, telemetry, non-critical state
  updates)
- Try/except blocks around `await session.execute(...)`,
  `session.add(...)`, `session.flush(...)`, or `session.commit(...)`
  that lack a corresponding `await session.rollback()` in their
  except clause
- Helper functions that swallow exceptions as "graceful
  degradation" (`return None`, `return []`, etc.)

## How to audit (D17 cleanup work)

A grep-based first pass:

```bash
# Find all try/except blocks in app/services/ + app/agents/
grep -rB5 "except.*:" backend/app/services/ backend/app/agents/ \
  | grep -B5 "session\|db\.execute\|db\.add\|db\.flush"

# Find functions that catch broad Exception and DON'T rollback
grep -rA15 "except Exception" backend/app/services/ backend/app/agents/ \
  | awk '/except Exception/,/^[a-z]/' \
  | grep -L "session.rollback\|db.rollback"
```

Better second pass: a custom AST visitor that identifies
`try`/`except` blocks containing `await session.execute(...)` (or
similar DB calls) where the `except` body lacks `await
session.rollback()`. The visitor should exempt cases where the
outer caller is known to handle rollback (e.g., the calls in
[evaluation.py::evaluate_with_retry](../../backend/app/agents/primitives/evaluation.py)
which manages its own transaction lifecycle).

For each instance found:

1. Determine whether the function runs inside a caller-managed
   transaction (high risk — adds rollback) or owns its own
   session (lower risk — already calls commit/rollback explicitly)
2. Add the rollback per the correct shape above
3. Add a pin-test mirroring the
   `test_session_recovers_after_load_goal_contract_failure` shape
   from D10 Commit 5

## Cross-references

- [docs/followups/goal-contracts-schema-divergence.md](./goal-contracts-schema-divergence.md)
  — the specific incident that surfaced the pattern
- [backend/app/services/agentic_snapshot_service.py](../../backend/app/services/agentic_snapshot_service.py#L211)
  — canonical fixed example
- [backend/app/agents/billing_support.py](../../backend/app/agents/billing_support.py)
  — second fixed example
- [backend/tests/test_services/test_snapshot_service_rollback.py](../../backend/tests/test_services/test_snapshot_service_rollback.py)
  — the pin-test pattern (synthetic always-failing query trigger
  keeps the contract under test even after the original bug is
  fixed)
- [docs/lessons.md](../lessons.md) — historical Python-level
  guidance; this asyncpg-protocol-level lesson is broader and
  belongs in the next lessons.md update too

## Tag

**Non-blocking; class-level pattern requiring a future audit.** D10
Checkpoint 2 fixed the two instances blocking D10's verification
path. A broader codebase audit + per-instance fix work belongs in
D17 cleanup per the Pass 3j scope, or earlier opportunistically as
related code is touched (e.g., D11 senior_engineer migration may
naturally surface more instances if it runs into transaction
poisoning during sandbox execution paths).

---

# Three sibling patterns (added during D10 Checkpoint 3 sign-off)

The D10 Checkpoint 3 in-flight discoveries surfaced three more
patterns of "implicit-state assumption that the code makes about
its environment." All three share the meta-pattern: **the code
silently assumes a setup step has happened, and works in test or
dev because the assumption happens to hold there, but breaks (or
nearly breaks) in a different setup.** The asyncpg-rollback gap
above is the headline instance; these three are siblings worth
tracking together so a future D17 audit can sweep all four classes
at once.

## Sibling 1: JSONB-cast in raw SQL strings

**The pattern.** SQL strings written against JSONB columns
sometimes include explicit `::jsonb` casts (e.g., `INSERT INTO
student_inbox (..., metadata, ...) VALUES (..., :meta::jsonb, ...)`).
asyncpg's parameter parser sees `:meta::jsonb` as the parameter
`meta:` followed by literal `:jsonb` — but `:` after a
parameter name isn't valid syntax, so the whole statement raises
`PostgresSyntaxError: syntax error at or near ":"`.

**The fix in every case.** Drop the `::jsonb` cast. Postgres
auto-casts the bound text value to the column's declared type
(JSONB) at INSERT time because the column type is JSONB; the cast
is redundant on the bind. Pass the JSON as a string via
`json.dumps(...)`.

**Three known instances fixed during D10.** All three share the
exact same shape:

1. `student_inbox.metadata_` server_default
   ([commit 21ff4f6](../../backend/app/models/student_inbox.py))
   — fixed in Commit 5 by swapping `func.cast("{}", JSONB)` →
   `sa_text("'{}'")`. SQLAlchemy-side cast, not a raw SQL bug
   per se, but same principle: drop the explicit cast, let the
   column type do the work.
2. `escalate_to_human` INSERT
   ([commit 2032f69](../../backend/app/agents/tools/agent_specific/billing_support/escalate_to_human.py))
   — fixed in Commit 6 by dropping `:meta::jsonb` from the
   INSERT statement. Caught immediately by the Checkpoint 3
   escalation smoke; would have surfaced at first real
   escalation in production otherwise.
3. `entitlement_service.grant_signup_grace` and
   `grant_placement_quiz_session`
   ([entitlement_service.py:639,694](../../backend/app/services/entitlement_service.py#L639))
   — also use `:meta::jsonb`, but currently work because the
   D9 implementer happened to test only the unit path that
   dispatches them (which goes through pg_session). **Production
   path may or may not have hit them yet.** Worth fixing
   prophylactically as part of the D17 audit since the pattern
   will eventually fire identically.

**How to audit.** Grep for `::jsonb` in raw SQL strings across the
codebase:

```bash
# All raw-SQL ::jsonb casts
grep -rn '::jsonb' backend/app/

# More targeted: ::jsonb inside text(...) blocks
grep -rB2 -A2 'text(' backend/app/ | grep '::jsonb'
```

For each hit, decide:
- **Drop the cast** if the column is declared JSONB at the
  schema level (most cases). Postgres infers from the column type.
- **Keep the cast** only if the value is being inserted into a
  non-JSONB column where Postgres needs the explicit type
  conversion (rare — usually a sign of a different design bug).

## Sibling 2: Registration-on-import patterns

**The pattern.** Several modules in the codebase use the "import
the module → side-effect-register something in a global registry"
pattern. The agentic OS uses this in three places:

1. **Agent classes** auto-register via `AgenticBaseAgent.__init_subclass__`
   when their module is imported. The
   `_agentic_loader._AGENTIC_AGENT_MODULES` list + the
   `load_agentic_agents()` call in FastAPI lifespan cover this.
2. **Tool decorators** (`@tool(...)`) register with the
   `tool_registry` when their module is imported. Imports are
   chained through `app.agents.tools.__init__` (themed modules)
   + `app.agents.tools.universal.__init__` + `app.agents.tools.agent_specific.__init__`.
3. **Proactive triggers** (`@proactive`, `@on_event`) register
   schedules + webhook subscriptions at decorator-fire time.

The trap: **calling the loader in tests doesn't always cover the
production path.** `tests/conftest.py` and many test fixtures
import the agent + tool modules implicitly during their own setup
(via the `client` fixture, the `db_session` fixture, etc.). So
tests pass even when the production app has no equivalent import
trigger. The dev-vs-prod divergence is invisible from inside
the test suite.

**Known instance.** `ensure_tools_loaded()` was not called in
`app/main.py` lifespan as of D10 Checkpoint 3
([commit 2032f69](../../backend/app/main.py)). The agent-specific
billing tools never registered in the FastAPI process; the first
real escalation request would have failed with
`Tool 'escalate_to_human' not registered`. The Checkpoint 3
smoke caught it; production would have failed silently for the
"phantom escalation" cohort until the inbox went unanswered.

**How to audit.** For each side-effecting import in the codebase:

```bash
# Find side-effect-only imports (the "noqa: F401" tag)
grep -rn 'noqa: F401' backend/app/

# Find decorator-based registrations
grep -rE '^@(tool|register|on_event|proactive)' backend/app/

# Cross-reference: is each registration source loaded at app
# startup? lifespan in main.py + celery_app boot are the two
# entry points.
grep -nE 'import|load_|ensure_' backend/app/main.py backend/app/core/celery_app.py
```

For each registration source, verify it has at least one
production code path that triggers the import. A registration
that only fires from a test fixture is a bug.

**Recommended generalization (if the audit finds more gaps):** add
a `register_all_at_startup()` helper in `app/agents/__init__.py`
(or similar) that calls every loader explicitly. Lifespan calls
that one helper; nothing depends on import-graph coincidence.

## Sibling 3: Test isolation around clear-able registries

**The pattern.** Tests that depend on a process-local registry
state (the agentic registry, the tool registry, structlog
processors, etc.) need either per-test restoration of that state
OR direct construction that doesn't go through the registry at
all. Some test fixtures call `clear_X_registry()` between tests
for isolation; downstream tests that expect the registry to be
populated then fail with `KeyError` or "not registered" errors
that have nothing to do with the test's actual purpose.

**Known instance.** D10 Checkpoint 3's three phantom-escalation
pin tests at
[tests/test_agents/test_billing_support.py](../../backend/tests/test_agents/test_billing_support.py)
originally fetched `BillingSupportAgent` from `_agentic_registry`.
Tests in `tests/test_agents/primitives/` call
`clear_agentic_registry()` per test (legitimately — they're
exercising the registry). When pytest collected both files in
the full regression, the primitives tests ran first
(alphabetical), cleared the registry, and the pin tests ran
later with an empty registry → `KeyError: 'billing_support'`.
Tests pass in isolation; fail in the full regression. Confusing.

**The fix.** Pin tests now construct `BillingSupportAgent()`
directly instead of going through `_agentic_registry`. Same
class, no implicit-state assumption.

**How to avoid in future tests.** When writing a test that needs
an agent (or a tool, or any registered singleton):

- **Prefer direct construction.** `MyAgent()` is honest about
  what's being tested.
- **If the test must go through the registry** (e.g., it's
  testing the registry itself), restore registry state in a
  per-test fixture: save the dict before the test, replace its
  contents at teardown.
- **Never assume "the registry is populated because some other
  test already imported the module."** That's the trap that
  causes test ordering to matter.

This will bite again as D11+ adds more agent tests. The
recommendation should land in the test-writing guide whenever
that doc gets written.

## Sibling 4: Parallel LLM client construction bypassing the factory

Discovered during MiniMax M2.7 activation (Phase 2 verification gate,
2026-05-05) when the canonical agentic endpoint returned 500 with
`RuntimeError: ANTHROPIC_API_KEY not set; Supervisor cannot run`.

**The shape:** `app/agents/llm_factory.py:build_llm()` is the
intended single entry point for constructing LLM clients — it
priority-routes between MiniMax and Anthropic based on which key is
configured. But two callers built `ChatAnthropic(...)` directly,
bypassing the factory entirely:

- `app/agents/supervisor.py:_build_supervisor_llm` — needed
  Supervisor-specific params (`temperature=0.1`, `max_tokens=1500`,
  `max_retries=2`) that the factory's surface didn't expose
- `app/agents/primitives/safety/llm_classifier.py:_build_safety_classifier_llm`
  — needed safety-specific params (`temperature=0.0`,
  `max_tokens=200`, `timeout=1.5`, `max_retries=0`)

Each builder hardcoded `settings.anthropic_api_key` and raised on
its absence. **Fatal under MiniMax-only configuration** — every
agentic request 500'd because Supervisor was the first hop.

**Why the Phase 1.1 audit missed this:** the audit grepped
`estimate_cost_inr` and `model_name` callers, both correct grep
targets *for cost tracking*. Neither would have surfaced
`ChatAnthropic(` constructors that don't track cost — those
parallel builders were invisible to a cost-grep population.

**The discipline:** when investigating any subsystem with an
abstraction layer, grep BOTH the abstraction AND the underlying
primitive. Each captures a different population:

- Abstraction grep (`build_llm()`, `estimate_cost_inr`) → callers
  using the intended interface
- Primitive grep (`ChatAnthropic(`, `AsyncSession(`, `redis.Redis(`)
  → callers bypassing the abstraction entirely

The primitive grep is the one that catches the bypass.

**Fix:** each builder gets a MiniMax priority check at the top
mirroring `build_llm`'s shape, while preserving its existing
per-builder params unchanged. The route-to-MiniMax branch and the
route-to-Anthropic branch differ only in model + key + base_url.

## Meta-pattern across all four

The asyncpg rollback, JSONB cast, registration-on-import,
test-isolation, and parallel-LLM-client patterns share one shape:
**code that works because some unstated environmental assumption
happens to hold, and breaks (or silently misbehaves) when the
assumption changes.**
Each instance was discovered the same way: an end-to-end
verification path (smoke test, full regression, manual
verification) hit the failure mode, and the in-isolation tests
that should have caught it didn't because they shared the same
environmental assumption.

The systemic mitigation: **end-to-end verification is not
optional.** Pin-tests in isolation catch logic bugs but miss
integration bugs. Smoke + E2E catch integration bugs. Both are
necessary. The D10 Checkpoint discipline — every checkpoint
ends with both a regression sweep AND a smoke verification —
caught all four of these patterns. D11+ should preserve the
same discipline.
