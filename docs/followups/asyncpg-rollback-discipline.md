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
- [`billing_support_v2._record_interaction`](../../backend/app/agents/billing_support_v2.py)
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
- [backend/app/agents/billing_support_v2.py](../../backend/app/agents/billing_support_v2.py)
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
