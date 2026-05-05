# LLM cost tracking — silent-zero gaps after MiniMax activation

**Status:** Open — six known auxiliary cost-write paths still emit ₹0
under MiniMax. Resolution scheduled across D12, D13, D17.
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
`_PRICING_USD_PER_1M`. Unknown models return `0.0` silently. With
MiniMax M2.7 added to the pricing table during this activation, calls
that pass `"MiniMax-M2.7"` get priced correctly. Callers that
hardcoded an Anthropic model identifier still emit ₹0 even when the
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
- **`tailored_resume_service.py` cost tracking** → fix during D12
  (career bundle includes resume area). Writes to
  `tailored_resumes.cost_inr` per migration 0037.
- **`jd_decoder_service.py` cost tracking** → D17 cleanup OR accept
  as deferred. Writes to a dedicated `jd_decode_runs.cost_inr` table.
- **`readiness_orchestrator.py` cost tracking** → D17 cleanup OR
  accept as deferred. Accumulates cost into a service-internal
  variable; touch the model resolution at the same time the orchestrator
  is reviewed.
- **`base_agent.log_action` telemetry** → no fix. Legacy BaseAgent
  agents are retired by D17 as the canonical agentic endpoint absorbs
  all dispatch; fixing telemetry on a code path scheduled for deletion
  is wasted effort.
- **Layer 2 safety classifier + Critic cost tracking** → pre-existing
  gap (not MiniMax-induced; these never tracked their own cost),
  D17 cleanup territory. The classifier and Critic build their own
  LLMs via `build_llm()` and never call `estimate_cost_inr` on the
  results.

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
