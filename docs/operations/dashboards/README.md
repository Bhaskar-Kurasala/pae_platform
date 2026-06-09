# Dashboards (D19.1 CP4)

Backend-agnostic dashboard definitions. Each `*.json` file in this
directory describes one dashboard against the canonical metric
substrate from D19.1 CP2 (`aicareeros_*` series in
`app/core/metrics.py`).

## Why JSON-as-code

Dashboards rot. `docs/operations/runbooks.md` references panels by
ID; if a panel's query drifts away from the metric backing it, an
on-call engineer at 2am opens the runbook link and sees an empty
chart. Versioning the dashboards in git puts the dashboard in the
same review surface as the metric-emission code that powers it —
a metric rename in `app/core/metrics.py` should land in the same
PR as the dashboard query update.

## Backend-agnostic shape

Each dashboard JSON document conforms to:

```json
{
  "id": "string — file stem matches",
  "title": "Human-readable title for top of dashboard",
  "owner": "engineering | ops | founder | role-name",
  "description": "One sentence on what this dashboard is for",
  "runbook": "../runbooks.md#section",
  "time_range_default": "1h | 24h | 7d",
  "panels": [
    {
      "id": "panel-slug",
      "title": "Panel title",
      "panel_type": "counter_rate | histogram_quantile | gauge | table | status",
      "description": "What this panel shows",
      "query": {
        "metric": "aicareeros_*",
        "aggregation": "rate | sum | avg | quantile",
        "by": ["label", ...],
        "quantile": 0.95
      }
    }
  ]
}
```

Backends (Grafana / Datadog / Honeycomb / etc.) get a thin
transformer at D19.1 CP5 backend-decision time. Any backend that
accepts Prometheus-shape metrics can render these queries without
schema rework.

## Owners

Per D-F: every dashboard has exactly one named owner responsible
for keeping it accurate. Unowned dashboards are deleted, not
maintained.

| Dashboard | Owner |
|---|---|
| api-health.json | engineering |
| agent-health.json | engineering |
| cost.json | founder + ops |
| db-health.json | engineering |
| auth-events.json | ops |
| operational.json | engineering |

## How dashboards relate to alerts (D19.2 preview)

Each dashboard panel is queryable as an alert source. D19.2 picks
the panels that constitute incident-grade signals (5xx rate,
agent error rate, cost burn, DB pool exhaustion, login failure
rate, queue depth) and authors threshold-driven alerts against
the same queries. A dashboard panel without an alert is "trend
aware"; one with an alert is "incident grade". Both consume this
substrate.

## Smoke test

`tests/test_core/test_d19_cp4_dashboards.py` validates that:

1. Every JSON file parses + matches the schema.
2. Every metric referenced by a panel query resolves to a metric
   actually registered in `app/core/metrics.py`.
3. Every panel query's labels appear on the referenced metric's
   labelnames (catches typos like `agent` vs `agent_id`).
4. Every runbook link points at a section that exists in
   `docs/operations/runbooks.md` (D19.4 populates the bodies; CP4
   scaffolds the headings).

The test runs against the same canonical REGISTRY as the
discipline tests in CP2, so dashboard drift is caught at CI.
