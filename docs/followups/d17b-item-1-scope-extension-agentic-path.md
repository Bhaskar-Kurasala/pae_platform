# D17b ITEM 1 — scope extension (agentic-path cost tracking)

**Status:** ✅ Resolved at D18 Phase B pre-CP2 bug remediation 2026-05-09.
**Origin:** Scope-gap finding; D17b ITEM 1's cost-tracking-silent-zero
fix was applied to the agent layer's instrumentation but missed
several v2/agentic agents that authored their own LLM call paths.

## What this is

D17b ITEM 1 closed "cost-tracking silent zero" by retrofitting the
canonical `_track_llm_usage(ctx, response)` + `_finalize_action_log`
machinery onto `AgenticBaseAgent`. The instrumentation infrastructure
itself was correct and complete.

What D17b ITEM 1 did NOT verify: that every existing v2/agentic
agent **calls** `_track_llm_usage(ctx, response)` after each
`llm.ainvoke(...)` round. Five agents missed the convention:

| Agent                  | LLM-calling sites missing _track_llm_usage |
|------------------------|---:|
| resume_reviewer_v2     | 1  |
| career_coach_v2        | 1  |
| study_planner_v2       | 1  |
| example_learning_coach | 2  |

(`tailored_resume_v2` is deterministic — no LLM call — so cost=0
is correct for it. The other 4 supervisor-orchestrated agents
that DID have the call — billing_support, senior_engineer,
mock_interview, practice_curator, project_evaluator — were fine.)

The result: every supervisor-orchestrated invocation through
`/agentic/default/chat` that landed on one of the 5 broken agents
recorded `agent_actions.cost_inr = 0.0` in the audit row, despite a
real LLM call having clearly happened.

## Surfacing

Phase B CP1 journey (f) regression guard caught it via
`agent_actions.cost_inr` assertion (saw 0.0 + `output_data.llm_calls = 0`
despite a substantive LLM-synthesized resume review). The fix sites
were identified by `grep -c '_track_llm_usage' backend/app/agents/*.py`.

## Resolution

5 sites patched (1 each in 3 agents + 2 in example_learning_coach):

```python
response = await llm.ainvoke(messages)
self._track_llm_usage(ctx, response)  # ← BUG-CP1F fix
```

Verified end-to-end:
  * journey (f) cost-tracking test: pass (was xfail-strict).
  * journey (e) career-coach test: pass (was xfail-loose under
    batch — auto-resolved).
  * journey (d) mock-interview test: pass (BUG-CP1D fix; mock
    interview was already correctly instrumented; un-xfailed
    after schema fix).

## Discipline going forward (worth a note in agent-authoring docs)

Future agent authors should treat `_track_llm_usage(ctx, response)`
as a non-optional convention, parallel in shape to "always call
parent class super().__init__()" in OOP. The instrumentation
infrastructure is opt-in by author convention; missing a call
doesn't break execution but breaks the cost-tracking audit
contract silently.

A CP2 or CP3 candidate test: smoke that exercises every
@register'd agent and asserts `cost_inr > 0` for any agent that
actually performs an LLM call (deterministic agents like
tailored_resume_v2 exempted via capability flag). Would catch any
future agent author missing the convention at CI time.

## Cross-references

  * `docs/followups/bug-cp1f-cost-tracking-zero-on-agentic-path.md`
    — full diagnosis + resolution with per-agent table.
  * `docs/architecture/d17b-closure.md` — D17b's original
    closure (the fix that this scope-extension complements).
  * `backend/app/agents/agentic_base.py` — the instrumentation
    infrastructure (correct as-is).
