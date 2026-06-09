# BUG-CP1F — cost_inr=0 on /agentic/default/chat path

**Status:** ✅ **CLOSED** at pre-CP2 bug remediation 2026-05-09 (commit B).
**Severity at discovery:** MEDIUM (cost tracking regression;
invalidated D17b ITEM 1's contract for the supervisor-orchestrated path).
**Origin:** D18 Phase B CP1 journey (f) authoring, 2026-05-09.
**Surfaced by:** test_cp1_journey_f_resume_reviewer.py
(@pytest.mark.xfail strict=True, Convention A).
**Closed by:** Adding `_track_llm_usage(ctx, response)` calls after
`llm.ainvoke(...)` in 4 v2/agentic agents.

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

## Resolution (2026-05-09)

Diagnosis-before-fix per architect's directive surfaced the actual
root cause was NOT in the supervisor orchestration layer at all —
it was in the v2 agent implementations themselves.

`agentic_base._finalize_action_log` correctly computes `cost_inr` from
`ctx.extra["_llm_usage"]` accumulator. `agentic_base._track_llm_usage`
correctly pushes onto that accumulator from a response. But **5 of
8 v2/agentic agents never call `_track_llm_usage`** after their
`llm.ainvoke(...)` rounds, leaving the accumulator empty:

| Agent                 | _track_llm_usage calls | Status before fix |
|-----------------------|-----------------------:|-------------------|
| resume_reviewer_v2    | 0                      | broken            |
| career_coach_v2       | 0                      | broken            |
| study_planner_v2      | 0                      | broken            |
| example_learning_coach| 0                      | broken (2 sites)  |
| tailored_resume_v2    | 0                      | OK (deterministic; no LLM call) |
| billing_support       | 3                      | ✅                |
| senior_engineer       | 4                      | ✅                |
| mock_interview        | 1                      | ✅                |
| practice_curator      | 1                      | ✅                |
| project_evaluator     | 2                      | ✅                |

The pattern is per-agent: `_track_llm_usage` is opt-in instrumentation
each agent must call after its own LLM rounds. D17b ITEM 1 added
the canonical accumulator-+-finalize machinery; agents authored
without applying the convention end up with cost_inr=0.

### Fix applied

5 sites patched (+1 in resume_reviewer_v2, +1 in career_coach_v2,
+1 in study_planner_v2, +2 in example_learning_coach):

```python
response = await llm.ainvoke(messages)
self._track_llm_usage(ctx, response)  # ← BUG-CP1F fix
```

### Verification

  * journey (f) `test_resume_reviewer_records_cost_inr_for_real_llm_call`:
    xfail dropped; passes with cost_inr > 0.
  * journey (e) `test_career_coach_responds_with_role_aware_guidance`:
    xfail-loose dropped; passes consistently in batch (BUG-CP1E
    auto-resolved by this fix).
  * Full CP1 journey suite: 21 passed + 3 xfailed (only stripe
    env-gated remain), up from 18 passed + 5 xfailed pre-fix.

### Pattern 22 / Pattern 29 angle (refined)

Initial hypothesis (orchestrator missing instrumentation) was
wrong. The actual shape is **per-agent author discipline drift**:
each agent must opt into cost-tracking by calling _track_llm_usage,
and 5 of 8 agents missed the convention. This is closer to Pattern
27 (test-fixture staleness as code evolves) at the agent-author
layer than Pattern 29 — the instrumentation infrastructure is
correct and ready; the consumers (agent authors) didn't all apply it.

Worth adding to the AgenticBaseAgent docstring (and any agent-
authoring doc) that `_track_llm_usage` MUST be called after every
`llm.ainvoke` for cost-tracking to work. Also worth a smoke test
that catches future authors missing the call (CP2-CP3 candidate).

## Cross-references

  * `backend/tests/playwright/journeys/test_cp1_journey_f_resume_reviewer.py` — verified.
  * `backend/app/agents/{resume_reviewer_v2,career_coach_v2,study_planner_v2,example_learning_coach}.py` — fixed.
  * `backend/app/agents/agentic_base.py` — the instrumentation
    machinery (correct as-is; just needed callers to use it).
  * D17b ITEM 1 closure — original cost-tracking contract;
    extended by this fix to cover all v2/agentic agents.

## Cross-references

  * `backend/tests/playwright/journeys/test_cp1_journey_f_resume_reviewer.py` — the xfailed test.
  * `backend/app/api/v1/routes/agentic.py` — orchestrator entry.
  * D17b ITEM 1 closure (`docs/closures/d17b-item-1-*`) — the original
    cost-tracking-silent-zero fix that this regression undermines.
