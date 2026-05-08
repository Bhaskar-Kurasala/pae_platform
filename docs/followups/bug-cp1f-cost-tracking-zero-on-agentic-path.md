# BUG-CP1F — cost_inr=0 on /agentic/default/chat path

**Status:** Open. **Severity: MEDIUM** (cost tracking regression;
not blocking, but invalidates D17b ITEM 1's contract for the
supervisor-orchestrated path).
**Origin:** D18 Phase B CP1 journey (f) authoring, 2026-05-09.
**Surfaced by:** test_cp1_journey_f_resume_reviewer.py
(@pytest.mark.xfail strict=True, Convention A).

## What this is

POST `/api/v1/agentic/default/chat` invokes the supervisor
orchestration, which dispatches to the appropriate agent (e.g.,
resume_reviewer, career_coach). The agent runs a real LLM call (the
synthesized response shows it landed — substantive resume reviews
generated). But the resulting `agent_actions` row has:

  * `cost_inr` = `0.0`
  * `output_data.llm_calls` = `0`
  * `output_data.input_tokens` = `0`
  * `output_data.output_tokens` = `0`

Despite a real LLM call having clearly happened.

## Why this matters

D17b ITEM 1 verified that `agent_actions.cost_inr` populates
unconditionally on every HTTP agent path. CP4 pre-flight verified
the same for `agent_invocation_log`. CP5's TestBudgetTracker depends
on `cost_inr` to attribute test costs to the budget ceiling. If the
supervisor-orchestrated path doesn't populate cost, then:

  * Phase B's budget tracker misses ~50% of real-LLM test cost
    (anything routed via /agentic/* doesn't count).
  * Production cost-ceiling enforcement against per-student daily
    spend (`mv_student_daily_cost`) under-counts.
  * D17b ITEM 1's "cost-tracking-silent-zero" closure note may
    have missed this orchestration path.

## Pattern 22 / Pattern 30 angle

This is the supervisor orchestration's projection of the
agent's payload — the agent runs, produces a result, the
orchestrator wraps it; somewhere in the wrap the cost-bookkeeping
fields get reset to zero (or the path bypasses the cost-recording
hook entirely). Reading the code path:

  * `backend/app/api/v1/routes/agentic.py:agentic_chat` →
    `AgenticOrchestratorService` (constructed lazily; see line 67-78).
  * `AgenticOrchestratorService.run(...)` calls into the agent's
    `execute()`. The agent calls LLM → cost is recorded **somewhere**
    — but the projection back to `agent_actions.output_data` shows
    zeros.

Investigation needed: which writer landed the `agent_actions` row,
and why are the cost fields zero?

## Fix scope (preliminary)

Probably one of:
  * The orchestrator wraps the agent's payload but doesn't propagate
    the `_llm_usage` accumulator into the output_data dict.
  * The cost-recording call fires against `agent_invocation_log` but
    not `agent_actions` for this path.
  * The supervisor projects a "summary" row that's distinct from the
    inner agent's row, and the summary row's cost is zeroed by design.

The CP4 pre-flight verified `agent_invocation_log.cost_inr` populates
on direct HTTP agent calls. Phase B should verify whether this also
holds for `/agentic/default/chat` — the answer determines fix scope.

## Verification when fix lands

1. Drop `@pytest.mark.xfail` from
   `test_cp1_journey_f_resume_reviewer.py::test_resume_reviewer_records_cost_inr_for_real_llm_call`.
2. Run under runner overlay; expect PASS with `cost_inr > 0`.
3. Add a CP3 traceability test that asserts
   `agent_invocation_log.cost_inr` ALSO populates for the /agentic/*
   path (separate from `agent_actions.cost_inr`).

## Cross-references

  * `backend/tests/playwright/journeys/test_cp1_journey_f_resume_reviewer.py` — the xfailed test.
  * `backend/app/api/v1/routes/agentic.py` — orchestrator entry.
  * D17b ITEM 1 closure (`docs/closures/d17b-item-1-*`) — the original
    cost-tracking-silent-zero fix that this regression undermines.
