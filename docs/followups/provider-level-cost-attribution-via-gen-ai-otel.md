# Provider-level cost attribution via gen_ai OTel conventions

**Status:** Open. Deferred-pending-trigger.
**Origin:** D19.3 closure (2026-05-13). Surfaced as scope question at
D19.3 D-C when cost-tracking dashboard authoring drew the line at
per-agent + per-student attribution and explicitly defered per-LLM-
provider attribution.
**Severity:** Tracked-not-blocking. Cohort-1 launch operations don't
need this; revisit on trigger.

## What's deferred

Cohort-1 cost attribution today:

  * **Per-agent** (granular enough): `aicareeros_agent_cost_inr` counter
    labelled by `agent_id`. The cost dashboard's `cost-rate-by-agent` +
    `top-cost-agents-today` panels surface this directly. The 20-ish
    registered agents bound the label cardinality.
  * **Per-student** (granular enough): `mv_student_daily_cost` matview
    aggregates `agent_invocation_log.cost_inr` by `(user_id, day_utc)`.
    The cost dashboard's `students-near-or-at-ceiling` panel surfaces
    this directly.

What's deferred:

  * **Per-LLM-provider** (Anthropic vs MiniMax vs future providers).
    The platform routes through `app/agents/llm_factory.py`; the
    chosen provider lives on the response's `response_metadata.model`
    string but isn't a metric label.
  * **Per-model-version** (which specific Anthropic model — Sonnet 4.6
    vs Haiku 4.5 vs Sonnet 4.7 — produced the cost). Model version is
    captured in `agent_actions.output_data['llm']['model']` per D10
    Checkpoint 3 + the MiniMax routing fix, but isn't dimensionalized
    in the cost dashboard.
  * **Per-token-class** (input vs output, cache-hit vs cache-miss).
    Output tokens are typically 4–8× the input-token cost (per D19.1
    CP5 research). A per-token-class breakdown would let cost-burn
    analysis distinguish "agent emitting too much" from "agent reading
    too much context."

## Why deferred

Anthropic's OpenTelemetry support for LLM call instrumentation uses
the OTel project's `gen_ai` semantic conventions
(`gen_ai.system="anthropic"`, `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, etc.). As of 2026-05 these conventions
are still in **experimental status** with the OTel project — they
can shift in backwards-incompatible ways over the next 12-18 months.

Per D19.1 CP5 research (`d19-1-observability-backend-decision.md`):
*"The gen_ai semantic conventions are still experimental and will
shift over D19.3 / D19.4 timeframe. Honeycomb's wide-event query
model adapts to attribute renames at investigation time without
re-authoring dashboards; β's pre-authored LLM dashboards (paid SKU)
carry higher convention-churn rework cost."*

Building production cost attribution on experimental wire format
risks lock-in to a format that changes shape mid-deployment. The
right move at cohort-1 stage is: ship per-agent + per-student
attribution today (which empirically answers every cohort-1 cost
question we've seen), wait for gen_ai conventions to stabilize,
then build the per-provider / per-model / per-token-class
attribution against stable conventions.

## Re-evaluation triggers

Return to this deliverable when ANY of:

  1. **Anthropic OTel gen_ai conventions reach stable status.** The
     OTel project's spec page is the canonical signal; watch
     https://github.com/open-telemetry/semantic-conventions for
     the `gen_ai` namespace promotion from experimental to stable.
  2. **Cohort-1 cost analysis surfaces a specific question existing
     per-agent attribution can't answer.** Examples that would
     trigger:
     - "Which model version is driving the cost increase?" — model
       version isn't a metric dimension; needs per-model attribution.
     - "Is the cache-hit rate degrading?" — token-class breakdown
       needed.
     - "Which agent is most exposed to Anthropic vs MiniMax cost
       differential?" — per-provider breakdown needed.
  3. **Provider mix changes.** Adding a third LLM provider beyond
     Anthropic + MiniMax materially shifts the relevance: with two
     providers + 20 agents, per-agent attribution captures most of
     the signal. With four providers + 20 agents, the per-provider
     dimension becomes load-bearing for unit-economics decisions.

## What's in scope when re-evaluated

When the trigger fires, the deliverable extends:

  1. **`app/core/metrics.py` cost metric**: extend
     `AGENT_COST_INR_TOTAL` (or split into a new
     `aicareeros_agent_cost_inr_by_provider_model` counter) with
     `provider` and `model_version` labels. Cardinality stays bounded
     by the provider catalog × the active model versions (typically
     <20 unique combinations). The existing per-agent counter remains
     for backwards compatibility with current dashboards.
  2. **`agent_invocation_log` schema extension**: add `provider`
     (Text, indexed) and `model_version` (Text, NOT indexed unless
     query patterns demand). Backfill historical rows by parsing
     `output_data['llm']['model']` where available. Add migration
     numbered against the next-available revision ID (after 0067).
  3. **Cost dashboard extension**: add panels for
     `cost-by-provider-today` and `cost-by-model-version-today` to
     `cost.json`. The per-cohort placeholder remains separate (still
     deferred to pre-cohort-2).
  4. **Dashboard discipline test**: extend the
     `test_dashboard_panel_metrics_are_registered` test in
     `tests/test_core/test_d19_cp4_dashboards.py` to recognize the
     new labelled metric.

Estimated cost when re-evaluated: ~₹2-4 (schema migration +
metric extension + dashboard panel authoring + closure-time
verification).

## Cross-references

- D19.1 backend decision (Anthropic OTel maturity caveat): [`docs/architecture/d19-1-observability-backend-decision.md`](../architecture/d19-1-observability-backend-decision.md)
- D19.1 observability overview (open D-G items): [`docs/architecture/d19-1-observability-overview.md`](../architecture/d19-1-observability-overview.md)
- D19.3 cost dashboard: [`docs/operations/dashboards/cost.json`](../operations/dashboards/cost.json)
- Cohort attribution (sibling deferral, different trigger): [`docs/followups/cohort-membership-modeling.md`](cohort-membership-modeling.md)
- D19 deferred work inventory: [`docs/followups/d19-deferred-alerting-and-runbooks.md`](d19-deferred-alerting-and-runbooks.md)
