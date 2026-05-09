# D19.1 — Observability backend decision

**Status:** Recommendation drafted at D19.1 CP5 close (2026-05-09).
**Founder approval gate:** decision is NOT locked until founder
signs off (see "Founder approval" section at the bottom).
**Author:** Claude Code session (D19.1 CP5).

D-G of the locked architectural decisions deliberately deferred
backend choice from substrate-flip CPs (CP1 logging, CP2 metrics,
CP3 tracing) to closure. Rationale at decision time: a 1-2 day
backend evaluation depends on cost projections at cohort-1 scale,
ops familiarity, and integration with whatever Anthropic
observability hooks exist. Locking architect-led delays the
substrate work for no quality gain.

We now have the substrate (~₹17-23 cumulative D19.1 cost) and
can make the choice with empirical data.

---

## Three candidates

### α — Self-hosted Prometheus + Loki + Tempo + Grafana on Fly.io

The OSS-stack approach. Each pillar has a dedicated open-source
backend that ingests OTLP and exposes a query interface; Grafana
unifies the UI. Hosting all four on Fly.io as a sibling
deployment to the platform itself gives us full ownership of the
data path.

### β — Datadog

Managed SaaS. Single-vendor for logs / metrics / traces /
dashboards / alerting / on-call paging, all correlated by trace
context. The most-mature observability suite on the market with
the broadest integration ecosystem.

### γ — Honeycomb

Trace-first SaaS, also hosting metrics and logs. Purpose-built
for high-cardinality OTel data; query model is event-centric
rather than metric-centric (every span is a wide event you can
slice arbitrarily). Native OTel ingestion as the primary
contract.

---

## Scoring matrix (6 dimensions × 3 candidates)

### Dimension 1 — Monthly cost at cohort-1 scale

**Volume baseline (per the prompt):** ~100 users, ~10K agent
invocations/day, ~300K/month. Our substrate produces:

  * **Logs:** structlog JSON to stdout. CP1 sampling defaults
    are conservative (INFO 100%, DEBUG 1%) for launch; production
    target is INFO 10%. At cohort-1 scale, INFO 100% gives
    ~1-5 GB/month; INFO 10% gives ~100-500 MB/month.
  * **Metrics:** Prometheus scrape of /metrics. 15 D-D canonical
    metrics × ~50 unique label combinations × 1/15s scrape cadence
    = trivial volume (<1MB/day).
  * **Traces:** CP3 head-based sampling at 1% baseline. ~300K
    invocations/month × 1% = ~3K root spans/month + child spans
    (per request: 1 FastAPI + ~10 SQL + ~3 LLM + ~3 tool = ~17
    spans). Total ~50-60K spans/month at 1%; under tail-sampling
    "include errors + p99 latency" the volume can climb 2-3x.
    Plan for ~150-200K spans/month at production sampling.

| Candidate | Pricing model | Estimated monthly cost (cohort-1) | Scaling note |
|-----------|---------------|------------------------------------|--------------|
| **α** Fly.io self-hosted | Compute for 4 services (Prometheus, Loki, Tempo, Grafana). 256MB-1GB RAM each + persistent volumes. ~$15-30/mo for the cluster. **Important distinction:** Fly.io's own managed Prometheus is free at our metric volume — but that's *metrics only*. The full observability stack (Loki for logs, Tempo for traces, Grafana for unified UI) still needs self-hosted compute. "Metrics-free" doesn't generalize to "observability-free"; α ships the metrics pillar via Fly's managed offering and self-hosts the other three. The $15-30/mo estimate is for the three self-hosted services. | **~$15-30/mo** | Linear in compute. At 1K users (~10x): ~$50-100/mo. At 10K users: ~$200-500/mo + ops overhead climbs faster than dollars. |
| **β** Datadog | $36-47/host/mo APM (must license matched Infra hosts) + $0.10/GB log ingest + $1.70/M log index events + $5/M custom metrics + $1.06/M trace events. Our scale: 1 backend host + 1 worker host = 2 APM × $36 = $72; logs ~$0.50/mo ingest + $5/mo index; metrics free in baseline; traces $1/mo. Plus mandatory Infra Pro $15/host = $30. | **~$110-180/mo** | At 1K users: 2-3 hosts + 50GB log = ~$300-500/mo. At 10K users: $1500-3000/mo (Datadog's well-known pricing cliff territory). |
| **γ** Honeycomb | Free tier: 20M events/mo + 100M time series + 60-day retention. Our scale: ~150K-200K spans + ~50K log events + metric series = ~250K events/mo, **far under free tier**. Pro tier kicks in at 20M events ($130/100M events beyond). | **$0/mo** | At 1K users: ~2.5M events/mo, still inside free tier. At 10K users: ~25M events/mo, just over → ~$130/mo. Step function at the free-tier threshold; cost stays sublinear with users. |

**Score:** γ wins decisively. β is 10-15x more expensive at
cohort-1 scale; α is competitive but adds ops burden.

### Dimension 2 — Ops team familiarity

**State of the team:** the platform is currently a one-person
operation (founder + Claude Code agentic engineering).
"Ops team familiarity" reduces to "founder's prior exposure"
plus "what Claude Code can stand up reliably given existing
substrate evidence."

**Unknown to me; surfaced honestly:** I do not have direct
knowledge of which of these the founder has used in prior roles.
The recommendation should not over-weight this dimension without
that input.

| Candidate | Familiarity (estimated) |
|-----------|-------------------------|
| **α** Self-hosted | Prometheus / Grafana are the most-common observability stack in the industry. High likelihood of prior exposure. Loki + Tempo are Grafana Labs' own newer additions; less familiar than Prometheus/Grafana. |
| **β** Datadog | Common in mid-size+ companies; possible from prior employment. |
| **γ** Honeycomb | Less mainstream; expertise tends to be deliberately acquired rather than incidental. |

**Score:** unknown without founder input. Surface in the
approval section.

### Dimension 3 — Integration with Anthropic observability

The prompt explicitly flagged: "investigate; does Anthropic
offer LLM-call observability hooks (latency, token count,
cost-attribution)? Which backends ingest cleanly? Surface
honestly — register as unknown if nascent rather than guess.
This has compound value for D19.3."

**State of the world (researched at CP5 authoring; maturity caveats explicit):**

  * **Anthropic OpenTelemetry support is EXPERIMENTAL, not
    stable.** This is the load-bearing caveat. Anthropic has
    "Claude Code Monitor" with documented OpenTelemetry export
    of token usage / cost / tool activity / session health, and
    the community ships
    `opentelemetry-instrumentation-anthropic` for auto-instrumenting
    the Python SDK. But: the gen_ai semantic conventions
    (`gen_ai.usage.input_tokens`, `gen_ai.system="anthropic"`,
    etc.) are still in *experimental status* with the OTel
    project as of 2026-05; the conventions can shift in
    backwards-incompatible ways over the next 12-18 months.
    Treating this as production-ready integration would
    over-state the maturity. Realistic posture: instrument
    against gen_ai conventions because that's where the
    industry is converging, but expect to chase the
    convention's stabilization through D19.3 / D19.4 timeframe.
  * **What this means for us:** every modern observability
    backend that ingests OTLP (all three candidates) can
    consume the experimental gen_ai telemetry today. The
    fragility is in the conventions, not the transport. As
    conventions stabilize, dashboards / saved queries that
    referenced specific attribute names may need re-authoring;
    that cost is the same across all three backends.
  * **Per-backend (with maturity caveats):**
    - **α** Prometheus + Loki + Tempo + Grafana: ingest OTLP via
      collector. Grafana has community plugins for LLM-cost views
      (varying maturity); cost-attribution dashboards must be
      authored. No vendor-supported "Anthropic integration"
      page — community plugins are best-effort.
    - **β** Datadog: ships an "LLM Observability" product
      (separate SKU, additional cost on top of the APM/Logs
      bundle quoted in Dimension 1). Native dashboards for
      OpenAI/Anthropic exist but specialize on the *stable*
      surface (token counts, latency); the experimental
      gen_ai conventions are tracked but not primary. Highest
      "no work for the stable surface" path; convention
      churn lands as dashboard rework like everywhere.
    - **γ** Honeycomb: ships a documented "Anthropic Usage &
      Cost Monitoring" page (free tier). Wide-event model
      reads any `gen_ai.*` attribute natively without
      dashboard pre-authoring; per-trace cost breakdown is a
      single ad-hoc query, so convention shifts cost less
      because the queries are typed at investigation time.
  * **D19.3 impact:** D19.3 is per-cohort cost attribution. All
    three candidates support this since the substrate
    (CP1 user_id contextvar + CP2 cost_inr metric + CP3 span
    attributes) emits the data; differences are UI ergonomics
    only. No backend choice is forced by D19.3 — but the
    convention-stabilization timeframe overlaps D19.3, so
    whichever backend lands should be one whose query model
    tolerates evolving attribute names. γ's wide-event model
    handles this best; β's pre-authored dashboards handle it
    worst.

**Score:** γ edges β edges α (closing the previously over-stated
β advantage). All three work cleanly with our existing substrate;
γ gains a small edge for tolerating gen_ai convention churn
better than dashboard-pre-authored backends.

### Dimension 4 — Query performance for on-call use cases

The 2am incident criterion: <5 minutes from incident-page to
root-cause hypothesis. Per the prompt's specific use cases:

| Use case | α (self-hosted) | β (Datadog) | γ (Honeycomb) |
|----------|-----------------|-------------|---------------|
| **All errors for a specific user_id in last 1 hour** | LogQL query against Loki — works but learning curve. | Logs explorer query: `@user_id:abc-123 status:error`. Native UI. | "Where user_id = X, level = error"; trivial Honeycomb query. |
| **p95-latency outliers across all agents in 24h** | PromQL: `histogram_quantile(0.95, ...)` against Prometheus. Standard query. | APM service map + p95 panel out of the box. | Wide-event groupby on agent_id with p95 calculation; instant. |
| **Cross-correlate: agent error spike + DB pool saturation + Celery queue depth at same wall-clock** | Grafana dashboard with three panels at same time-range. Manual eye correlation. | Datadog dashboard with cross-pillar correlation; auto-anomaly highlighting. | Single BubbleUp query across the wide-event store; the "is X correlated with Y" question is Honeycomb's flagship. |
| **Trace single request: FastAPI → agent → LLM → DB write** | Tempo trace view; works given our W3C propagation from CP3. | Datadog trace view with auto-correlated logs/metrics. | Honeycomb trace view; flagship feature. |

**On-call diagnostic clarity ranking:** γ > β > α. Honeycomb's
wide-event model is purpose-built for "explore arbitrary
slices of high-cardinality data fast." For a small team where
the on-call engineer is also the architect, this matters more
than feature breadth.

**Score:** γ wins on the criterion the prompt named primary.

### Dimension 5 — Vendor-lock risk

| Candidate | Lock risk | Notes |
|-----------|-----------|-------|
| **α** Self-hosted | **Zero.** Full data ownership. Migration to managed later is `kubectl exec` + dump + import. | Migration cost is human time, not data hostage cost. |
| **β** Datadog | **High.** Historical data export exists but is rate-limited and egress-fee-bearing. Switching at 12 months means losing 12 months of dashboards / saved searches / alert configs (the dashboards-as-code from CP4 mitigate this for us specifically — that's the whole point of the JSON format). | Datadog's pricing escalates aggressively with scale, which the founder would feel before the lock-in pain. |
| **γ** Honeycomb | **Medium.** OTel-native ingest = instrumentation is portable (no vendor SDK in code). Historical query data is in Honeycomb's columnar store; export is via API but more friction than self-hosted. | The CP3 substrate ships standard OTel; switching from γ to α to β requires only a destination URL change + a re-author of dashboards. |

**Score per the prompt's tertiary weighting:** α > γ > β. But
remember: dashboards-as-code (CP4) and OTel-native instrumentation
(CP3) together substantially reduce vendor-lock cost for any of
the three.

### Dimension 6 — Pre-launch decision criterion alignment

The prompt's locked criterion order:

> "1. on-call can debug a 2am incident in <5 minutes" (primary)
> "2. cost" (secondary)
> "3. vendor-lock" (tertiary)

| Criterion | Winner | Margin |
|-----------|--------|--------|
| 2am incident in <5min | **γ** | clear (wide-event model > metric-first model for ad-hoc questions) |
| Cost | **γ** | decisive ($0 vs $15-30 vs $110-180) |
| Vendor-lock | α (γ a close second) | small (CP3+CP4 substrate already minimizes lock cost across all three) |

---

## Summary scorecard

| Dimension | α self-hosted | β Datadog | γ Honeycomb |
|-----------|---------------|-----------|-------------|
| Monthly cost (cohort-1) | $15-30 | $110-180 | **$0** |
| Ops familiarity | unknown (best-guess high for Prometheus/Grafana) | unknown | unknown |
| Anthropic integration (experimental gen_ai conventions) | community plugins, manual | paid LLM SKU, dashboards-pre-authored (churn cost higher) | **best — wide-event model tolerates convention churn at investigation time, free integration page** |
| Query performance | functional | strong | **best for our use cases** |
| Vendor-lock | **zero** | high | medium |
| Primary criterion (2am < 5min) | functional | strong | **strongest** |
| Aggregate (criterion-weighted) | second | third | **first** |

---

## Recommendation: γ — Honeycomb

**Reasoning:**

1. **Primary criterion alignment.** Honeycomb's wide-event
   model is purpose-built for the "ad-hoc slice of high-cardinality
   data under time pressure" use case the 2am-incident criterion
   names. A small team where the on-call engineer is also the
   architect benefits disproportionately from a query model that
   doesn't require pre-defining the dimensions you'll later want
   to slice on.

2. **Cost alignment.** Free tier covers cohort-1 entirely.
   Step-function to ~$130/mo at ~10K users — but that's a
   problem we want to have. Compare to β where the same scale
   would be $1500-3000/mo.

3. **Anthropic-specific integration is documented, free, AND
   tolerant of the experimental conventions' churn.**
   Honeycomb ships an explicit "Anthropic Usage & Cost
   Monitoring" page on the free tier. More importantly: the
   gen_ai semantic conventions are still experimental and will
   shift over D19.3 / D19.4 timeframe. Honeycomb's wide-event
   query model adapts to attribute renames at investigation
   time without re-authoring dashboards; β's pre-authored LLM
   dashboards (paid SKU) carry higher convention-churn rework
   cost. D19.3's per-cohort cost attribution slots in cleanly
   regardless of backend, but γ tolerates the conventions
   stabilizing best.

4. **OTel-native ingestion** matches what CP3 already ships.
   No SDK lock-in: switching backends later is a destination URL
   change. Combined with CP4's dashboards-as-code, the
   reversibility cost is low (see below).

5. **Why not α (self-hosted)?** Cheaper-than-Honeycomb's-paid
   tier at small scale, but not cheaper than γ's free tier.
   Adds ops burden (4 services to keep up). Prometheus is a fine
   metric backend but its query model doesn't match the ad-hoc
   investigation pattern that dominates a small team's on-call.
   Reconsider if cohort grows past 10K users AND ops capacity
   exists to run the cluster well.

6. **Why not β (Datadog)?** Dominant on feature breadth but
   strictly dominated on the primary criterion (Honeycomb's
   wide-event model wins the 2am question) AND on cost. The
   "you might use it later" features don't earn the 5-15x cost
   premium at our stage.

---

## Migration path (if recommendation lands)

The substrate work in CP1-CP4 is backend-agnostic by design. The
migration is operational, not architectural:

1. **Honeycomb account + ingest key.** Founder creates org;
   ingest key goes into Fly secrets (`HONEYCOMB_API_KEY`).

2. **OTLP exporter pointed at Honeycomb.** Set
   `OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io` and
   `OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=$HONEYCOMB_API_KEY`
   on backend and worker Fly apps. CP3's tracing.py picks this
   up automatically — `init_tracing()` already wires the
   `OTLPSpanExporter` based on the env var.

3. **Logs ingest.** Honeycomb ingests logs via OTLP-as-events.
   Two options:
     a. Configure structlog's processor chain to also emit OTLP
        log records (small change to `app/core/logging.py`).
     b. Use Fly's log shipper to forward stdout JSON to a
        Honeycomb HTTP ingest endpoint.
   Option (b) is lower change-cost; option (a) gives richer
   correlation.

4. **Metrics ingest.** Two options:
     a. Honeycomb ingests Prometheus metrics via OTLP-metrics.
        Wire `OTLPMetricExporter` from `opentelemetry-exporter-otlp`
        next to the existing tracing exporter. ~30 lines in
        `app/core/metrics.py`.
     b. Keep Fly's free managed Prometheus for the metric pillar
        and only send logs+traces to Honeycomb. Honeycomb queries
        are then traces+logs only; metric panels live in Grafana
        against Fly's Prometheus.
   Option (b) is lighter-weight; option (a) puts everything in
   one query surface.
   **Recommended:** start with (b) for launch, evaluate (a)
   post-launch when query patterns surface.

5. **Dashboard import.** Honeycomb has a public board API. The
   6 dashboard JSONs from CP4 transform via a small script:
   `panel.query.metric` → Honeycomb dataset name; `aggregation`
   + `quantile` → Honeycomb visualization config. ~150 LoC
   transformer; one-time write.

6. **Runbook anchors.** No change — `docs/operations/runbooks.md`
   sections already match dashboard ids.

7. **Alerts (D19.2 surface).** Honeycomb's "Triggers" feature
   takes a saved query + threshold + notification channel.
   D19.2 picks panel queries from CP4 and authors triggers
   against them.

**Estimated migration cost:** ~₹2-3 (small amount of code to
write the metric exporter wiring + dashboard transformer +
ingest verification). One developer-day equivalent. Founder
approval is the gating step, not engineering effort.

---

## Reversibility assessment

If 6 months in we want to switch from γ to β (or α):

| Asset | Switching cost |
|-------|----------------|
| Code instrumentation | Zero. CP3 is OTel-native; only the destination URL changes. |
| Dashboards | Re-import. CP4's JSONs transform to any backend via a backend-specific small script. ~150 LoC per backend. |
| Saved queries / triggers (D19.2 onward) | Manual recreation. Triggers are backend-specific. Estimate: ~1 day for 10-20 alerts. |
| Historical data | **Lost** in any backend switch. 60 days at γ's free tier; longer retention at β. Plan accordingly: archive critical data via Honeycomb's export API before the switch. |
| Runbook anchors | No change. |

**Total switch cost:** 1-2 developer-days + retention loss
above the free-tier window. Lower than typical SaaS-switching
cost because the substrate is OTel-portable.

---

## Risks and unknowns

1. **Founder familiarity is unknown.** If the founder has
   significant prior Datadog experience, "5-min-to-find-the-thing"
   might rank β higher than γ for *this* founder despite γ's
   structural advantages. Surface for approval discussion.

2. **Honeycomb's free-tier survival.** 20M events/mo is generous
   today; vendors trim free tiers periodically. Acceptable risk —
   our reversibility is good, and the paid tier ($130/100M events)
   is still 5-10x cheaper than β at equivalent scale.

3. **gen_ai semantic conventions are still standardizing.**
   They'll likely shift over the next 12-18 months. All three
   backends will track the standard; pinning to gen_ai conventions
   in our spans (CP3 substrate) is the right move regardless of
   backend.

4. **Tail-sampling deferred to backend collector.** D-E specifies
   tail-based sampling; CP3 ships head-based and the prompt
   defers tail-based to CP5 backend choice. **Honeycomb supports
   refinery** (Honeycomb's own tail-sampling collector) as a
   first-class extension. If γ is approved, refinery wires into
   the migration as step 4b. Estimated: ~1 day to author
   refinery rules matching D-E (errors + p99 latency 100% retain;
   1% baseline for healthy traces).

---

## Founder approval

The architect prompt explicitly named founder approval as the
locking gate. **This document is a recommendation, not a
decision.**

**Founder, please indicate:**

  - [ ] **Approve γ Honeycomb.** Migration begins per the path
    above. D19.2 (alerting) targets Honeycomb Triggers.
  - [ ] **Choose α self-hosted.** Architect re-authors migration
    path for self-hosted; D19.2 targets Grafana Alerting.
  - [ ] **Choose β Datadog.** Architect re-authors migration path
    for Datadog; D19.2 targets Datadog Monitors. Cost discussion
    included.
  - [ ] **Defer.** Specify what additional information is needed
    (specific use case to validate, prior-experience verification,
    etc.).

After founder approval lands, a separate post-CP5 commit updates
this document with the locked decision + executes the migration
steps. Until then, D19.1 is sealed at the substrate level; D19.2
is blocked on backend choice (alerting attaches to the chosen
backend's alerting surface).

## Cross-references

- Saved D19.1 prompt: [`docs/claude-code-prompts/d19-1-prompt.md`](../claude-code-prompts/d19-1-prompt.md) — D-G defers backend choice to this document.
- D19.1 overview: [`docs/architecture/d19-1-observability-overview.md`](d19-1-observability-overview.md) — canonical D19.2-D19.5 reference.
- D19.1 logging conventions: [`docs/architecture/d19-1-logging-conventions.md`](d19-1-logging-conventions.md).
- CP4 dashboards: [`docs/operations/dashboards/`](../operations/dashboards/).
- CP4 runbooks scaffold: [`docs/operations/runbooks.md`](../operations/runbooks.md).

## Sources consulted (CP5 research, 2026-05-09)

- Fly.io Metrics docs + community pricing discussion: [Fly.io Metrics docs](https://fly.io/docs/monitoring/metrics/), [Fly.io community: managed Prometheus pricing](https://community.fly.io/t/how-to-integrate-fly-io-managed-prometheus-to-scrape-metrics-from-external-source/16042)
- Anthropic + OpenTelemetry instrumentation: [Honeycomb Anthropic Usage & Cost Monitoring docs](https://docs.honeycomb.io/integrations/anthropic-usage-monitoring), [SigNoz Anthropic monitoring with OTel](https://signoz.io/docs/anthropic-monitoring/), [OpenTelemetry for AI Systems (Uptrace)](https://uptrace.dev/blog/opentelemetry-ai-systems)
- Datadog pricing analyses (2026): [Datadog official pricing](https://www.datadoghq.com/pricing/), [Datadog real-cost analysis (OneUptime)](https://oneuptime.com/blog/post/2026-03-18-the-real-cost-of-datadog/view), [Datadog pricing breakdown for small teams (Nurbak)](https://nurbak.com/en/blog/datadog-pricing/)
- Honeycomb pricing: [Honeycomb official pricing](https://www.honeycomb.io/pricing), [Honeycomb OpenTelemetry integration page](https://www.honeycomb.io/platform/opentelemetry)
