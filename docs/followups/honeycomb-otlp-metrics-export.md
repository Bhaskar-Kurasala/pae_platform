# Honeycomb OTLP metrics export wiring

**Status:** Open. Tracked-not-blocking.
**Origin:** Honeycomb backend lock (2026-05-13). Surfaced as the
auth-mismatch resolution path between Fly's Prometheus scraper
(no Basic auth support) and our `/metrics` endpoint (fail-closed
Basic auth contract per D19.1 CP2).
**Severity:** Low — the lock window ships traces-to-Honeycomb,
which is the load-bearing pillar for cost-spike alerting; metrics
serve as an ad-hoc curl surface until this follow-up lands.

## What's deferred

The initial Honeycomb backend lock (2026-05-13) routed **traces**
to Honeycomb via `OTLPSpanExporter` and left **metrics** on the
platform's `prometheus_client` registry exposed at `/metrics`
with HTTP Basic auth. The lock doc
([`docs/operations/honeycomb-backend-lock.md`](../operations/honeycomb-backend-lock.md))
documents the auth-mismatch and the chosen path: wire
`OTLPMetricExporter` so metrics flow directly to Honeycomb's
`/v1/metrics` endpoint via the same OTLP/HTTP transport as
traces; Fly's `[metrics]` block in `fly.toml` stays commented
out indefinitely.

What's NOT yet wired:

  * `OTLPMetricExporter` in `app/core/metrics.py` — needs ~20 LoC:
    construct the exporter when `OTEL_EXPORTER_OTLP_ENDPOINT` is
    set (mirrors the trace path in `app/core/tracing.py:203-213`),
    register a periodic export reader against the existing
    `prometheus_client` registry, configure the export interval
    (Honeycomb expects ~15-60s; matches Prometheus scrape cadence).
  * Backend boot wiring — call the new
    `init_metrics_export()` from `app/main.py` after
    `init_tracing()`. Idempotent; no-op when env unset.
  * Confirm `prometheus_client` collectors export cleanly via OTel
    — the OTel Python SDK has a `prometheus_client` bridge
    package (`opentelemetry-exporter-prometheus` or similar);
    verify the exact name + version at wiring time. If the bridge
    package doesn't fit, fallback: read REGISTRY samples on a
    timer + manually construct OTel metric instruments. The
    bridge approach is preferred (less code to maintain).

## Re-evaluation trigger

Ship this when ANY of:

  1. **Daily founder cost-review wants metric panels in Honeycomb
     UI alongside traces.** The friction point: switching between
     ad-hoc `curl /metrics` (text exposition; not visual) and
     Honeycomb's trace view (visual; missing metric series) breaks
     the sub-60-second daily glance discipline (D19.3 D-A).
  2. **A D19.2-deferred alert needs metric-shape backing in
     Honeycomb.** The deferred-alerts list at
     [`docs/followups/d19-deferred-alerting-and-runbooks.md`](d19-deferred-alerting-and-runbooks.md)
     names 11 metric-backed alerts that are paused at cohort-1
     scale. Re-enabling any of them in Honeycomb requires the
     metric series to be IN Honeycomb.
  3. **The Honeycomb free-tier event ceiling becomes a concern.**
     Honeycomb counts trace spans + metric data points + log
     events against the 20M/month free ceiling. At cohort-1 scale
     (1.5M projected), routing metrics adds maybe 0.5M more
     (15 metrics × scrape cadence). Still well under ceiling. If
     cohort growth pushes the projection past 15M/month, evaluate
     whether the metric exporter would push past 20M — at that
     scale, sampling the metric export becomes worth doing
     deliberately.

## Estimated cost when re-evaluated

~₹0-2. Pure substrate-config work; verification via the existing
D19.5 smoke suite + a new smoke for the metric-export path.

  * Pyproject.toml add: `opentelemetry-exporter-prometheus` (or
    equivalent) if a bridge package fits cleanly. ~30 sec at
    `uv lock`.
  * `app/core/metrics.py` extension: ~20 LoC.
  * `app/main.py` boot wiring: 2 LoC.
  * New unit test in `tests/test_core/`: verify `init_metrics_export()`
    is idempotent + no-op-safe when env unset, mirrors the
    `init_tracing()` shape from D19.1 CP3 tests.
  * Verification: founder confirms metric panels visible in
    Honeycomb UI 5-10 min after redeploy.

## What this unblocks

Migrating from manual-curl to Honeycomb-resident metrics unblocks:

  * Re-authoring D19.1 CP4 dashboards as Honeycomb boards. The
    JSON-as-code at `docs/operations/dashboards/` was authored
    backend-agnostic; the Honeycomb-side transformer (per the
    [D19.1 backend decision](../architecture/d19-1-observability-backend-decision.md)
    migration path step 5) becomes useful once metric data is in
    Honeycomb.
  * Re-engaging any of the 11 deferred metric-backed alerts when
    their re-evaluation triggers fire (per
    [d19-deferred-alerting-and-runbooks.md](d19-deferred-alerting-and-runbooks.md)).

## Cross-references

- Honeycomb backend lock: [`docs/operations/honeycomb-backend-lock.md`](../operations/honeycomb-backend-lock.md)
- D19.1 CP3 tracer wiring (the shape this follow-up mirrors): [`backend/app/core/tracing.py`](../../backend/app/core/tracing.py)
- D19.1 CP2 metric registry: [`backend/app/core/metrics.py`](../../backend/app/core/metrics.py)
- D19.1 backend decision (migration path): [`docs/architecture/d19-1-observability-backend-decision.md`](../architecture/d19-1-observability-backend-decision.md)
- Deferred-alerts inventory: [`docs/followups/d19-deferred-alerting-and-runbooks.md`](d19-deferred-alerting-and-runbooks.md)
