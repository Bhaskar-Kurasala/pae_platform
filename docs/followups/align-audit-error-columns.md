# Follow-up: align `error_message` storage across agentic-OS audit tables

**Owner:** _unassigned — pick up before the second agentic-OS migration._
**Status:** open
**Created:** 2026-05-02
**Triggered by:** D4 (`communication.py`) shipping while the
`agent_call_chain` table did not have a dedicated error column.

## Problem

The Agentic OS audit tables disagree on how to store error messages:

| Table | Error storage |
|---|---|
| `agent_tool_calls` | dedicated `error_message TEXT NULL` column |
| `agent_call_chain` | smuggled inside `result JSONB` as `{"error": "..."}` |
| `agent_escalations` | dedicated `reason TEXT` column |
| `agent_proactive_runs` | dedicated `error_message TEXT NULL` column |

D4 chose the JSONB-smuggle path on `agent_call_chain` to avoid a
schema bump for a single column. The decision is documented in the
`_audit` helper in `app/agents/primitives/communication.py` so it's
not invisible.

The cost: when an admin or oncall queries across the audit tables
("show me every failed agent action in the last hour, with the
error message"), the join has to pivot on `error_message` from three
tables and `result->>'error'` from `agent_call_chain`. Easy to
forget the JSONB extract; even easier to write a query that silently
under-reports.

## Proposed fix

Add a real `error_message TEXT NULL` column to `agent_call_chain`
in the next agentic-OS migration. Backfill is a one-liner:

```sql
UPDATE agent_call_chain
SET error_message = result->>'error'
WHERE result ? 'error' AND error_message IS NULL;
```

Update `app/agents/primitives/communication.py::_audit` to write
the column directly. Drop the "stash inside result" branch.

## Done when

- [ ] Migration adds the column
- [ ] Backfill runs against existing rows
- [ ] `_audit` helper writes the dedicated column
- [ ] One ops query (`SELECT … FROM agent_call_chain WHERE
      error_message IS NOT NULL`) returns the same rows it would
      have via `result->>'error'`

## Why this isn't urgent

Today there are zero rows in `agent_call_chain` (D4 just landed,
no agents call call_agent yet). The mismatch is a future ergonomics
problem, not a present correctness problem. Address it in the same
migration that lands D6's `agent_proactive_runs` enhancements or
the first post-D8 cleanup, whichever comes first.

## References

- Decision in code: `backend/app/agents/primitives/communication.py`
  → `_audit()` docstring
- Migration: `backend/alembic/versions/0054_agentic_os_primitives.py`
  → see `agent_call_chain` columns (no `error_message`)
- Tool table for comparison: same migration → `agent_tool_calls`
  has the dedicated column
