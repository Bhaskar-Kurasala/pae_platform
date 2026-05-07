# `build_llm` does not expose `temperature`; Critic dropped the kwarg at Bug 18

## What

`app.agents.llm_factory.build_llm` has signature `(max_tokens, tier)` only. The Critic in `app.agents.primitives.evaluation._LLMCriticClient` originally called `build_llm(max_tokens=400, tier="fast", temperature=0.0)` to pin determinism for the verdict JSON. That call raised `TypeError` the first time it fired — surfaced at D13 CP3 because mock_interview is the first v2 agent with `uses_self_eval=True`.

D13 Bug 18 fix dropped the `temperature=0.0` kwarg from the Critic call site. The Critic now uses `build_llm`'s tier defaults (whatever Anthropic's / MiniMax's default temperature is). Both providers produce stable structured-output JSON at default temperature in D12 and D13 measurements, so Critic correctness does not require explicit temperature pinning today.

## Why deferred

Threading `temperature` through `build_llm` is a real signature change touching every D10–D13 caller (`career_coach_v2`, `senior_engineer`, `study_planner_v2`, `resume_reviewer_v2`, `tailored_resume_v2`, `mock_interview_v2`, plus the Critic). The diff is small; the surface-area review across six callers and two provider routes (Anthropic SDK, MiniMax-compatible endpoint) is what makes this its own deliverable.

## Triage

- **D14 (practice_curator / project_evaluator)** — if either of those agents needs explicit temperature control for their evaluation rubric, do this work then. Their structured outputs are score+rationale shapes similar to the Critic; same default-temperature stability argument should apply, but worth measuring before deciding.
- **D17 cleanup** — otherwise, schedule with the other build_llm surface tightenings.
- **Now** — do nothing. The Critic is correct without temperature pinning; D12+D13 v2 agents have never needed it; no agent has reported nondeterministic structured-output failures.

## Cross-reference

- [backend/app/agents/primitives/evaluation.py:340](backend/app/agents/primitives/evaluation.py#L340) — Critic's `build_llm` call site (post-fix).
- [backend/app/agents/llm_factory.py:70](backend/app/agents/llm_factory.py#L70) — `build_llm` signature.
- [backend/tests/test_agents/test_critic_build_llm_signature.py](backend/tests/test_agents/test_critic_build_llm_signature.py) — Bug 18 regression test; pins the call site against the actual signature so future drift fails CI.
- D13 CP3 closure — full Bug 18 history and cascade analysis.
