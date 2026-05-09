# Cost-spike alert (Honeycomb Trigger)

D19.2 D-A Alert 1. The first of the two operational alerts shipped
at cohort-1 launch scope.

**Status:** authored as configuration only at D19.2 closure.
**Live execution gated on:** the post-D19.1-CP5 backend-lock commit
that wires `OTEL_EXPORTER_OTLP_ENDPOINT` + `HONEYCOMB_API_KEY` Fly
secrets and starts shipping events to Honeycomb. Until ingestion
is live this trigger cannot be authored against an empty dataset.

## What it fires on

A 24h-window sum of `aicareeros_agent_cost_inr` (D19.1 CP2 D-D
canonical metric) exceeding `DAILY_COST_SPIKE_INR_THRESHOLD`.
The metric increments on every successful agent invocation in
both v1 (`BaseAgent.log_action`) and v2 (`AgenticBaseAgent._finalize_action_log`)
paths; sum across all `agent_id` labels gives platform-aggregate
cost.

## Threshold by cohort scale

| Cohort size | Suggested threshold | Reasoning |
|-------------|--------------------|-----------|
| 20 users | ₹500/day | Per-student typical-day average (₹100-₹150) plus 1.5x burst margin |
| 50 users | ₹1500/day | Same per-student baseline at 50x; 1.5x margin |
| 100 users | ₹2500/day | Same per-student baseline at 100x; tighter margin since outliers smooth out at scale |

Founder calibrates against **observed** typical-day totals from
the first week of cohort-1 traffic (the `cumulative-cost-today`
panel in `dashboards/cost.json` shows the rolling baseline).

## Honeycomb Trigger configuration

```
Dataset:    aicareeros (or whichever dataset name the backend-lock
            commit chooses; usually the OTel service.name resource)
Query:
  visualize: SUM(aicareeros_agent_cost_inr)
  time range: last 24 hours
  no group-by labels (single number)
Threshold:
  > {DAILY_COST_SPIKE_INR_THRESHOLD env var, e.g. 500}
Frequency:
  every 30 minutes
Recipients:
  - Email: founder@aicareeros.com (or configured founder email)
  - Slack: #ops-alerts via Honeycomb Slack integration
            (founder configures Slack webhook URL in Honeycomb UI)
Cooldown:
  4 hours (don't re-page if the spike persists; 4h is enough to
  investigate + decide before the next page)
```

## What to do when it fires

The 30-minute "what does the founder do" runbook (full runbook
discipline parked at D-D — D19.4 territory):

1. **Open the cost dashboard:** `dashboards/cost.json` →
   `cost-rate-by-agent` panel. Which agent is burning?
2. **Check the cohort-events feed:** has any user been hitting
   the per-student daily ceiling repeatedly? (`kind="daily_cost_ceiling_hit"`
   events in cohort_events; see `cohort-events-review-process.md`).
3. **Check Sentry:** any error spike correlated with the cost
   spike? (LLM-provider issues sometimes cascade into runaway
   retries which present as cost burn.)
4. **Decide:** is this organic high usage (good news; investigate
   if it's sustainable cost), a buggy agent loop (bad news; tighten
   that agent's ceiling via env or per-student override), or an
   adversarial user (worst news; tighten that user's
   `daily_cost_ceiling_inr_override` to ₹0 immediately).

## How to silence during planned high-cost work

Two valid silencing mechanisms:

  * **Honeycomb Trigger pause** in the UI for the duration of the
    planned work (load test, prompt tuning batch, real-LLM Phase B
    sweep). Re-enable when work completes.
  * **Threshold raise** via `DAILY_COST_SPIKE_INR_THRESHOLD` env var
    bumped temporarily; revert post-work. Useful when the planned
    work is an estimated 2x normal traffic; raise threshold to 2.5x.

Avoid leaving the trigger paused indefinitely — mute > silence is
the canonical anti-pattern for paged alerts.

## Smoke test procedure

After the backend-lock commit lands and Honeycomb is ingesting:

1. Author the trigger per the configuration block above with
   threshold = current cumulative cost − ₹0.01 (i.e., guaranteed
   to fire on the next evaluation).
2. Wait 30 minutes for the next trigger evaluation.
3. Verify email + Slack notifications arrived.
4. Restore the threshold to the cohort-scale value above.

Document the smoke completion timestamp in
`docs/operations/alerts/CHANGELOG.md` (create if absent).

## Cross-references

- D19.1 substrate: [`docs/architecture/d19-1-observability-overview.md`](../../architecture/d19-1-observability-overview.md)
- Backend choice: [`docs/architecture/d19-1-observability-backend-decision.md`](../../architecture/d19-1-observability-backend-decision.md)
- Cost dashboard: [`docs/operations/dashboards/cost.json`](../dashboards/cost.json)
- Per-student ceiling: [`docs/operations/cost-ceilings.md`](../cost-ceilings.md)
- Cohort-events review: [`docs/operations/cohort-events-review-process.md`](../cohort-events-review-process.md)
