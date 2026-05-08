# LLM cost-tracking convention — enforcement

**Status:** Open. **Severity: MEDIUM** (each new agent author will
repeat the drift until enforcement lands).
**Origin:** D18 Phase B pre-CP2 institutional registration,
2026-05-09 (post BUG-CP1F remediation).

## What this is

`AgenticBaseAgent._track_llm_usage(ctx, response)` is the canonical
hook that lets `_finalize_action_log` compute `cost_inr`. Without
the call, every LLM round happens silently — the audit row records
`cost_inr=0.0`, the cost-ceiling enforcement at Layer 3 of
entitlements never sees the spend, and the budget tracker
under-counts.

D17b ITEM 1 added the canonical machinery. BUG-CP1F surfaced that
**5 of 8 v2/agentic agents authored across D12-D14** missed the
convention (resume_reviewer_v2, career_coach_v2, study_planner_v2,
example_learning_coach×2). The pattern: each new agent author wrote
their `run()` body modeled on a prior agent that also missed the
convention, so the drift propagated.

## Why the docstring isn't enough

`_track_llm_usage` is documented in `agentic_base.py` with example
usage. The docstring is the canonical reference, but it's
discoverable only when an author opens `agentic_base.py`. New
agent authors typically copy-modify a sibling agent's `run()` body
— if that sibling missed the call, the new agent inherits the bug.
4 of the 5 broken sites in BUG-CP1F follow this lineage.

## Two enforcement options

### Option A — CI lint

A static-analysis check that flags any function containing
`llm.ainvoke(` or `llm.invoke(` without a subsequent
`_track_llm_usage(` in the same function body. Implementation:
ruff custom rule, or a small AST-based check in
`backend/scripts/lint_agent_cost_tracking.py` invoked from CI.

  * Pros: catches the exact regression shape; fast feedback.
  * Cons: can't detect the call-via-helper case (e.g., a
    `_call_llm()` wrapper); susceptible to false negatives if
    the helper is one author away.

### Option B — Refactor call shape so tracking is impossible to skip

Wrap LLM invocation in a helper that does both the call and the
tracking:

```python
# Proposed helper on AgenticBaseAgent:
async def call_llm(self, ctx: AgentContext, llm: Any, messages: list) -> Any:
    response = await llm.ainvoke(messages)
    self._track_llm_usage(ctx, response)
    return response
```

Then enforce via convention: agents call `self.call_llm(...)`
instead of `llm.ainvoke(...)` directly. A complementary lint rule
flags any agent calling `.ainvoke(` directly outside this helper.

  * Pros: structurally impossible to skip tracking; no per-author
    discipline required.
  * Cons: requires migrating all 10 existing agent LLM call sites
    (modest); breaks if an agent needs custom LLM-call logic
    (rare; can be opted out with a documented escape hatch).

**Recommendation:** Option B (structural enforcement) for new
agents authored after this lands; Option A as a backstop for
existing agents until they migrate. Together: the convention is
both structurally enforced AND lint-checked.

## When to implement

Defer until Phase B is complete. Phase B's job is journey testing,
not infrastructure refactoring. After Phase B closure (CP5), the
LLM-cost-tracking-convention work could be a focused 1-2 hour
deliverable.

If a new agent is authored before this lands, the agent author
should manually verify `_track_llm_usage` is called after each
`llm.ainvoke` in their `run()` body. The
`docs/followups/d17b-item-1-scope-extension-agentic-path.md` doc
captures this discipline.

## Cross-references

  * `docs/followups/bug-cp1f-cost-tracking-zero-on-agentic-path.md`
    — the bug that surfaced this enforcement gap.
  * `docs/followups/d17b-item-1-scope-extension-agentic-path.md`
    — the scope-extension finding that motivated this institutional
    registration.
  * `backend/app/agents/agentic_base.py` — the instrumentation
    surface that needs structural enforcement.
