# practice_curator sandbox verification — deferred per D-B

**Status:** Open. D14b CP1 locked decision D-B explicitly out-scoped sandbox-driven reference solution verification. The Pass 3c E8 spec mentioned "sandbox-runs a reference solution if provided" as a quality check; D14b ships without it.
**Created:** 2026-05-07 (D14b closure).
**Triage:** D17 cleanup or earlier — production-data trigger if curator generates unsolvable exercises >5%.
**Cross-references:** Pass 3c E8 line 688 (the spec's sandbox-runs mention); D11.5 sandbox infrastructure (`run_in_sandbox` + `run_tests` tools available); `app/agents/practice_curator.py` (current `run()` does not invoke sandbox).

## What

practice_curator generates exercises (problem statement + starter_code + test_cases + expected_solution_shape + evaluation_criteria + hints). The agent does NOT verify that the exercise is actually solvable — there's no automated check that:
- A reference solution implementing the described shape would pass the visible test cases
- The hidden test cases are solvable by the same shape
- The starter_code (when populated) is consistent with the test cases
- The estimated_time_minutes is realistic for the problem

D-B's locked decision: D14b ships text-only generation; a future deliverable adds sandbox-driven verification IF production data shows curator generates unsolvable exercises at meaningful rate.

## Implementation shape if/when this lands

The infrastructure exists from D11.5:
- `run_in_sandbox` tool registered with `execute:code_sandbox` permission
- `run_tests` tool wraps run_in_sandbox with pytest harness
- Both capability-gated; practice_curator's permissions would need `execute:code_sandbox` added

The wiring at the agent layer:

1. After the LLM produces a `PracticeCuratorOutput`, check if `exercise.exercise_type == "coding"` AND `expected_solution_shape` describes something concrete enough to attempt.
2. Generate a reference solution. Two options:
   - **Option A** (LLM-driven): a second LLM call with the prompt "implement the function described by `starter_code` + `expected_solution_shape` so all `test_cases_visible` pass." Cost: doubles per-call LLM cost.
   - **Option B** (skip when reference missing): the spec says "if provided" — interpret that as "the agent's prompt may include a `reference_solution` field; verify that against the test cases when present." Cost: zero per-call.

Option B is the cheaper interpretation and matches the spec's "if provided" wording. Recommend Option B unless production data shows Option A's quality gain justifies the cost.

3. Invoke `run_tests` with `code=reference_solution`, `test_code=<built from test_cases_visible>`, `framework="pytest"`.
4. If `passed != len(test_cases_visible)`, surface as a quality signal:
   - Log `practice_curator.unsolvable_exercise` with the exercise + test results for observability
   - Either: regenerate the exercise (cost-expensive retry path), OR ship the exercise with a `quality_warning` flag in `structured_output` that the orchestration layer can surface to the student ("this exercise is experimental — please flag if it's broken")

## Why D14b doesn't ship this

1. **No production data on failure rate.** D14b CP3 + CP4 verified 4 exercises; all 4 looked pedagogically sound on subjective review. No baseline for "how often does the LLM produce unsolvable problems?" — could be 0.5%, could be 15%. Building infrastructure for a problem we haven't measured is speculative.
2. **Cost doubles per call.** Even Option B's zero-cost-when-no-reference shape adds the run_tests call when a reference IS provided. Option A doubles every call.
3. **Spec's "if provided" leaves room for interpretation.** A future deliverable can interpret based on actual production failure shapes.

## Triage signals

Promote from "open follow-up" to "active work" when ANY of:
- Production audit shows curator-generated exercises flagged as broken by students at >5% rate
- senior_engineer evaluation flow (orchestration-layer post-curator) consistently fails to grade against curator's `evaluation_criteria` because the criteria don't fit the actual problem
- A specific D17+ deliverable (e.g., automated curriculum coverage testing) requires verified-solvable exercises
- Cost ceiling allows the per-call cost increase

## Cross-references

- [backend/app/agents/practice_curator.py](../../backend/app/agents/practice_curator.py) — current run() path; insertion point would be after `_parse_output(raw)` and before composing `payload["answer"]`
- [backend/app/agents/tools/agent_specific/sandbox/](../../backend/app/agents/tools/agent_specific/sandbox/) — D11.5 sandbox tools ready for practice_curator to declare
- Pass 3c E8 line 688 — original spec mention
- D14b CP1 closure — locked decision D-B
