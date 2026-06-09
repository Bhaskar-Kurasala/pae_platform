# LLM cost tracking — silent-zero gaps after MiniMax activation

**Status:** Substantially resolved.
- `tailored_resume_service.py` path RESOLVED in D12 CP3 Part C (2026-05-06).
- `jd_decoder_service.py` + `readiness_orchestrator.py` paths RESOLVED in
  D17b ITEM 1 (2026-05-08) via the refined-Path-B fix at the
  SubAgentResult/ParsedJd construction sites — see "D17b ITEM 1 resolution"
  section below.
- Two remaining gaps are cost-tracking-pipeline-broken shapes (D12 v2 agents
  + Layer 2 safety classifier / Critic), both architecturally distinct from
  the under-cost shape; deferred per triage below.
**Created:** 2026-05-05 (during MiniMax M2.7 activation, Phase 1.1
investigation).
**Cross-references:**
[llm_factory.py](../../backend/app/agents/llm_factory.py) (the
`_PRICING_USD_PER_1M` table this depends on),
[agentic_base.py](../../backend/app/agents/agentic_base.py)
(`_finalize_action_log` — the path that IS now correct after the
MiniMax activation work),
[Pass 3f §D.2](../architecture/pass-3f-entitlement-enforcement.md)
(cost ceiling mechanism, unaffected by this gap),
[Pass 3i §I.3](../architecture/pass-3i-scale-observability-cost.md)
(cost projections that need revision once production data accumulates).

## What this is

`estimate_cost_inr(model=..., input_tokens=..., output_tokens=...)`
in `llm_factory.py` does a string-keyed lookup against
`_PRICING_USD_PER_1M`. Unknown models return `0.0` silently.

**Two distinct failure shapes exist** (important for triage):

- **Silent-zero**: the caller passes an unknown model string → returns `0.0`.
  Example: a self-hosted model variant not in the pricing table.
- **Under-cost**: the caller passes a known model string, but the wrong one.
  Example: MiniMax runs the call, but the caller passes `"claude-sonnet-4-6"` →
  Sonnet pricing applied to a MiniMax call. Cost is non-zero but systematically
  incorrect (undercharged ~10x). This was the `tailored_resume_llm.py` shape.

Both shapes corrupt per-feature financial reporting. Under-cost is harder to
notice than silent-zero because the dashboard shows plausible-looking numbers.

With MiniMax M2.7 added to the pricing table during this activation, calls
that pass `"MiniMax-M2.7"` get priced correctly. Callers that
hardcoded an Anthropic model identifier still emit incorrect costs even when the
factory routed the actual call to MiniMax.

The investigation that produced this doc found six such callers
during Phase 1.1 of MiniMax activation. Each writes to its own
service-specific cost column or to telemetry — none feed
`agent_actions.cost_inr`, so the cost ceiling enforcement at
`mv_student_daily_cost` is unaffected. The damage is limited to
per-feature financial reporting (revenue analysis, cost-per-student
dashboards) which we do not yet have built.

## Triage assignments

- **`mock_interview_service.py` cost tracking** → fix during D13
  (mock_interview migration). The service writes its own
  `interview_turns.cost_inr` and `interview_sessions.total_cost_inr`;
  swap the hardcoded `model_for(tier)` argument for the live response's
  `response_metadata["model"]`.
- **`tailored_resume_service.py` cost tracking** → **RESOLVED in D12 CP3
  Part C** (2026-05-06). The actual bug was an **under-cost** shape, not
  silent-zero: `tailored_resume_llm.py`'s `generate()` returned
  `model_for("smart")` = `"claude-sonnet-4-6"` unconditionally, so MiniMax
  calls were priced at Sonnet rates. Fix: replaced the static sentinel with
  `response_metadata.get("model") or response_metadata.get("model_name")`,
  matching the convention in `agentic_base.py:_extract_llm_metadata`. Falls
  back to `model_for("smart")` when response_metadata is absent (stub LLMs,
  providers without this field). Unit tests in
  `tests/test_agents/test_llm_cost_tracking.py` pin both the live-model path
  and the fallback path.

- **D12 v2 agents (career_coach_v2, study_planner_v2, resume_reviewer_v2,
  tailored_resume_v2) cost columns NULL under MiniMax** → registered
  2026-05-07 (D12 CP4 closure). All 9 verification calls during Phase 4
  + post-cutover smoke produced `agent_actions.cost_inr = NULL` despite
  the underlying LLM calls completing successfully and `usage_metadata`
  being populated on the response. The `AgenticBaseAgent._finalize_action_log`
  cost-tracking path appears to not write through to the `agent_actions`
  row. This is distinct from the under-cost shape — it's a "tracking
  pipeline broken" shape. The cost ceiling enforcement view
  (`mv_student_daily_cost`) reads from `agent_actions.cost_inr`, so this
  affects D12 agents' cost ceiling enforcement: a MiniMax-routed
  career_coach call does NOT contribute to the daily cost cap. Pricing
  table is correct; the write isn't happening.

  Symptom debugging hint: `_track_llm_usage` is called during the
  AgenticBaseAgent execute() path; it appends to `ctx.extra["_llm_usage"]`.
  `_finalize_action_log` reads that accumulator. Under MiniMax, either
  the accumulator never gets populated OR the finalize path raises and
  fail-softs to a NULL cost_inr write. The structlog `llm.call` event
  IS emitting (verified during Phase 4), so `_merge_token_usage` runs;
  the issue is downstream. Triage: D17 or when production cost
  reporting becomes a blocker.
- **`jd_decoder_service.py` cost tracking** → **RESOLVED in D17b ITEM 1
  (2026-05-08).** See "D17b ITEM 1 resolution" section below.
- **`readiness_orchestrator.py` cost tracking** → **RESOLVED in D17b ITEM 1
  (2026-05-08), composes with the same fix.** The orchestrator reads
  `result.model` from SubAgentResult; once the SubAgentResult population
  is correct, the orchestrator inherits the correctness.
- **`base_agent.log_action` telemetry** → no fix. Legacy BaseAgent
  agents are retired by D17 as the canonical agentic endpoint absorbs
  all dispatch; fixing telemetry on a code path scheduled for deletion
  is wasted effort.
- **Layer 2 safety classifier + Critic cost tracking** → pre-existing
  gap (not MiniMax-induced; these never tracked their own cost),
  D17 cleanup territory. The classifier and Critic build their own
  LLMs via `build_llm()` and never call `estimate_cost_inr` on the
  results.

## D17b ITEM 1 resolution (2026-05-08)

**Architectural framing:** The "Path A vs Path B" framing from the D17a
STOP turned out to be a false dichotomy. The pre-flight audit at D17b
ITEM 1 surfaced that the two patterns operate at **different
architectural layers** and compose:

- **Path A** (response_metadata extraction at the leaf) is institutional
  in `agentic_base.py:587-616` (`_track_llm_usage`) and was the D12 CP3
  Part C fix in `tailored_resume_llm.py`. It's the canonical pattern for
  "what model actually ran" inside a single LLM call.
- **Path B** (structured contract field carried through the call stack)
  is institutional in `readiness_sub_agents.py` (the `SubAgentResult`
  dataclass with `model: str` field). It's the canonical pattern for
  passing the value across module boundaries to downstream consumers.

The receivers (`jd_decoder_service.py`, `readiness_orchestrator.py`)
were already on Path B and reading `result.model` correctly. The bug
was at the **value source**: the 8 SubAgentResult constructions in
`readiness_sub_agents.py` and the 1 ParsedJd construction in
`jd_parser.py` hardcoded `model=model_for(self.tier)` (intent), not
`model=<truth from response>`. Under MiniMax, this produced an
under-cost shape — Sonnet pricing applied to MiniMax M2.7 calls
(~10× over-attribution). Identical bug shape to the original
tailored_resume CP3 Part C bug, one architectural layer up.

**Fix shape (refined Path B — leaf extraction populates contract field):**

1. Added `_model_from(response) -> str | None` helper to
   `readiness_sub_agents.py`, mirroring the agentic_base.py pattern:
   prefer `response_metadata['model']`, fall back to `['model_name']`,
   return None when absent (signal to use intent fallback).
2. Updated all 4 success-path SubAgentResult constructions in
   `readiness_sub_agents.py` to use
   `model=_model_from(response) or model_for(self.tier)`.
3. Inlined the same extraction into `jd_parser.py` at its single
   ParsedJd construction (matching jd_parser's existing inline-style
   for `usage_metadata` extraction).
4. **Kept all 4 error-path SubAgentResult constructions unchanged**
   (`model=model_for(self.tier)`). No response exists yet at the
   error path; intent is the most honest signal of what the agent
   tried to use. The success/error asymmetry is load-bearing
   discipline — a future contributor changing this would silently
   destroy model attribution on every LLM failure.

**Tests at `backend/tests/test_agents/test_llm_cost_tracking.py`:**

- `test_readiness_sub_agent_captures_response_model_under_minimax`:
  pins the under-cost fix; fake response with
  `response_metadata={"model": "MiniMax-M2.7"}` produces
  `SubAgentResult.model == "MiniMax-M2.7"`.
- `test_readiness_sub_agent_falls_back_to_intent_when_no_response_metadata`:
  pins the fallback path for stub LLMs / providers without metadata.
- `test_readiness_sub_agent_error_path_keeps_intent_model`: pins the
  success/error asymmetry — LLM raises, SubAgentResult.model is
  `model_for(self.tier)`, not None or empty.
- `test_jd_parser_captures_response_model_under_minimax`: pins the
  parallel fix at jd_parser's single construction site.

**N=4 evidence chain resolved:**

1. D14c (rubric_grounding helper response model not captured) — RESOLVED transitively.
2. D17a (jd_decoder_service.py investigation STOP) — RESOLVED in D17b ITEM 1.
3. D15 CP3 (readiness_orchestrator.py turn-cost attribution) — RESOLVED transitively.
4. D15 CP4+CP5 (readiness verdict generator cost) — RESOLVED transitively.

The receivers all read `result.model`; once the population is correct
at the 9 leaf sites, the entire downstream cost-attribution graph is
correct. No additional consumer-side changes were needed.

**Pattern observation registered for canonical promotion:**
Path A and Path B are not alternatives. They compose at different
layers. Treating them as alternatives risks either (a) duplicating
extraction logic at every consumer (bad Path A) or (b) propagating
wrong values through structured fields (bad Path B). The composed
discipline: **extract at the leaf via Path A; carry across module
boundaries via Path B; the value source change happens at the
construction site, the abstraction stays.**

## What this means for Pass 3i §I.3

Cost projections in Pass 3i §I.3 are based on Anthropic pricing and
assume `cost_inr` is populated for all LLM calls. With MiniMax
activation:

- **Per-call costs are now ~10x lower** than Pass 3i §I.3
  projections (good news — projections were conservative ceilings,
  not floors).
- **Per-feature financial reporting** (jd_decoder revenue analysis,
  mock_interview cost-per-student, etc.) emits silent zero until each
  parent deliverable lands per the triage above.
- **`mv_student_daily_cost`** (the cost ceiling enforcement view)
  remains accurate because it only sums `agent_actions.cost_inr`,
  which IS being tracked correctly under the MiniMax activation work.

## Safety classifier tier divergence (registered 2026-05-05)

Under Anthropic, the Layer 2 safety classifier ran on Haiku 4.5 — a
small, fast model designed exactly for short-prompt classification
work. Under MiniMax (post-activation), it runs on M2.7, which is
MiniMax's large general model. Cost is fine (M2.7 is cheap). Latency
might not be: safety scans are on the hot path of every agentic
request, and a larger model means marginally higher per-call
latency.

**Not a launch blocker.** The classifier still has the 1.5s
SDK timeout + 2.0s `asyncio.wait_for` cap from Pass 3g §B.2.2; if
M2.7 exceeds those it falls back to Layer 1 (regex) verdict — a
logged degradation, not a hard failure.

**If post-launch safety latency becomes a concern**, the cause is
likely M2.7 doing classification work originally designed for a
Haiku-tier model. Three options:

1. Route safety classification to a separate small model if MiniMax
   adds tier support
2. Keep Anthropic as a parallel provider specifically for safety
   classification (re-add the ANTHROPIC_API_KEY check in
   `_build_safety_classifier_llm`, prefer it over MiniMax for this
   one builder)
3. Accept the latency and tune the safety timeout knobs upward —
   simplest if the budget allows

## When to revisit

When D17 closes, do a comprehensive cost-tracking sweep that:

1. Confirms all 6 aux paths now emit correct `cost_inr` under
   whatever LLM provider is active.
2. Backfills historical zero-cost rows if needed (or documents that
   backfill isn't possible because token counts weren't preserved).
3. Updates Pass 3i §I.3 projections with real production data — at
   that point we should have weeks of accumulated MiniMax usage to
   ground the per-feature unit economics.

## Cross-references

- [llm_factory.py](../../backend/app/agents/llm_factory.py)
  `_PRICING_USD_PER_1M` — the pricing table this depends on; expand
  here whenever a new model is introduced.
- [agentic_base.py](../../backend/app/agents/agentic_base.py)
  `_finalize_action_log` — the path that IS now correct after this
  activation work; new agents inheriting AgenticBaseAgent inherit the
  fix automatically.
- [Pass 3f §D.2](../architecture/pass-3f-entitlement-enforcement.md)
  — cost ceiling mechanism, unaffected by this gap.
- [Pass 3i §I.3](../architecture/pass-3i-scale-observability-cost.md)
  — projections that need revision when D17 closes.
