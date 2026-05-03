# Universal-tool permission scoping

**Status:** Open — deferred from D10 Checkpoint 1.
**Created:** 2026-05-03 (D10 Checkpoint 1 sign-off).
**Blocked by:** nothing — small refactor when scope-aware permissions
become valuable.

## The gap

Pass 3d §D.1 specifies the permission model for the universal
`memory_recall` tool as scope-aware:

> Permissions: `read:student_data` when scope=user;
> `read:cohort_data` for scope=agent / scope=global.

D10 Checkpoint 1 shipped the universal tools with a single
permission grant (`read:agent_memory` for `memory_recall` and
`memory_forget`, `write:agent_memory` for `memory_write`,
`write:audit_log` for `log_event`, none for `read_own_capability`).

**Why D10 deviated:**

- The single-permission shape matches the existing D3 stub
  (`recall_memory` / `store_memory`) declarations and what
  `AgenticBaseAgent.permissions` actually grants today.
- `AgenticBaseAgent.permissions` is currently
  `frozenset[str] = Field(default_factory=frozenset)` — i.e. agents
  default to **no permissions at all**, and the only existing
  `permissions` declaration anywhere in the codebase is on
  `AgenticBaseAgent` itself. Splitting the universal tools into a
  scope-aware permission set would break every consuming agent
  immediately because none would have either of the new permission
  strings granted to them.
- Per-call enforcement happens in `ToolExecutor.execute` via a set
  comparison (`spec.requires` ⊆ `context.permissions`). Adding
  conditional permission requirements based on input-arg values
  (e.g. "if `scope=user` then check X, else check Y") would need
  a richer `requires` declaration than the current
  `tuple[str, ...]` — that's a primitive change, not a tool
  change.

## What "fix" means

Two changes, in order:

1. **Define the canonical permission roster.** Pass 3d §C.1 lists
   them: `read:student_data`, `read:cohort_data`, `read:agent_memory`,
   `write:agent_memory`, `write:notifications`, `write:audit_log`,
   `execute:code_sandbox`, `external:github`, `external:youtube`,
   `external:email`, `admin:escalation`. The codebase currently only
   uses a subset; the full roster needs to be standardized as a
   typed enum or `Literal` set so typo-permissions get caught at
   import time.
2. **Extend the `@tool` decorator to support conditional permissions
   based on input args**, OR keep the simpler shape and accept that
   "permissions are a coarse-grained gate, finer-grained checks
   live in tool bodies." The latter is the cheaper choice and is
   what D10 effectively shipped.

## Why this isn't urgent

- No security risk in production: the universal tools are only
  callable from inside an agent's `run()` method, which is invoked
  via `call_agent` from the dispatch layer. Both layers already
  enforce entitlement-based access; the tool permission check is
  defense in depth, not the primary gate.
- No correctness risk: the universal tools work correctly today.
  The "fix" is about precision of declared intent, not behavior.
- The first agent that genuinely needs scope-aware permissions
  (probably `interrupt_agent` per Pass 3h, with its
  cross-student aggregator pattern) will surface the requirement.
  Until then, the current shape is fine.

## Recommended trigger

Revisit when the first of these happens:

- A migration deliverable (D11+) hits a tool body that needs
  `read:cohort_data` distinct from `read:student_data` — likely
  `interrupt_agent` or `practice_curator`
- A security review wants per-permission audit logging
- D17 cleanup naturally absorbs the canonicalization work

## Cross-references

- `docs/architecture/pass-3d-tool-implementations.md` §C.1 — the
  full permission roster
- `docs/architecture/pass-3d-tool-implementations.md` §D.1 — the
  scope-aware spec for `memory_recall`
- `backend/app/agents/tools/universal/memory_recall.py` — inline
  comment at the `requires=...` declaration referencing this
  follow-up
- `backend/app/agents/primitives/tools.py::ToolExecutor.execute` —
  the per-call enforcement site

## Tag

**Non-blocking; precision-of-intent issue.** D10 Checkpoint 1 ships
the universal tools with the simpler-permission shape; refining is
a follow-up when the first scope-aware requirement surfaces.
