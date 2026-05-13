# Honeycomb backend lock

**Status:** Lock config landed (2026-05-13); Fly secrets pending
founder execution.
**Owner:** founder (Honeycomb account + Fly secrets); architect
(config + verification docs).
**Cross-references:**
[D19.1 backend decision](../architecture/d19-1-observability-backend-decision.md),
[D19.1 observability overview](../architecture/d19-1-observability-overview.md),
[D19.5 readiness gate](../architecture/d19-5-pre-launch-readiness-gate.md) Section 2 Item 4.

The post-D19.5 deferred-ops commit that wires the OpenTelemetry
substrate (D19.1 CP3) to Honeycomb's ingest endpoint. After this
lands, the cost-spike Trigger (D19.2 Alert 1) can be authored
against live traffic; the founder-glance cost dashboards (D19.3)
can consume real spans + metric data.

---

## Architecture

D19.1 CP5 recommended γ Honeycomb (free tier — 20M events/month,
60-day retention). Founder approved.

The substrate is OTel-native:

  * **Traces** (D19.1 CP3) — `OTLPSpanExporter` wired in
    [`backend/app/core/tracing.py:206`](../../backend/app/core/tracing.py).
    Activates when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; no-op
    when unset.
  * **Metrics** (D19.1 CP2) — `prometheus_client` registry,
    exposed at `/metrics` with HTTP Basic auth (D19.1 CP2 fail-closed
    contract).
  * **Logs** — structlog JSON on stdout, Sentry breadcrumb bridge;
    Fly captures stdout natively. Honeycomb ingest deferred to
    log-shipper follow-up.

Migration path for this lock window (matches D19.1 CP5
[backend decision migration path](../architecture/d19-1-observability-backend-decision.md)
**option (b)** — start with traces over OTLP; metrics stay on
the Prometheus client; logs stay on stdout):

  * **Traces → Honeycomb** via OTLP/HTTP (the path this commit
    wires).
  * **Metrics → manual curl + ad-hoc** (the auth-mismatch with
    Fly's Prometheus scraper is documented below; `OTLPMetricExporter`
    wiring is a follow-up).
  * **Logs → stdout + Sentry breadcrumbs** (unchanged).

---

## Founder-side prerequisite (verify before running the secrets)

The agent doesn't create Honeycomb accounts. Founder owns these
steps once:

1. **Sign up at ui.honeycomb.io.** Free tier is sufficient for
   cohort-1 volume (~1.5M events/month projected; free tier ceiling
   is 20M events/month).
2. **Create a team / environment.** Default naming: team
   `aicareeros`, environment `production`. The environment name
   becomes the Honeycomb-side dataset prefix; pick stable.
3. **Generate an ingest API key.** Team Settings → Environments →
   `production` → API Keys → Create Key. Permissions: "Create
   datasets" + "Send events". Copy the key value (it's shown once;
   if lost, generate a new key — there's no recovery).

If any of these aren't done yet: **STOP** — Fly secret commands
below need the API key value. The remaining steps (Fly secrets
set, redeploy, verify) take ~10 minutes once the key is in hand.

---

## Fly secrets commands (founder execution)

Run these from the project root, replacing `<API_KEY>` with the
ingest key value:

```bash
# pae-platform — the API process. Spans on every HTTP request,
# every agent invocation, every DB call, every outbound HTTP call.
fly secrets set --app pae-platform \
  OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io \
  OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<API_KEY> \
  OTEL_SERVICE_NAME=aicareeros \
  OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production

# pae-platform-worker — Celery worker process. Spans on every
# task execution, propagated from the API via CeleryInstrumentor
# (D19.1 CP3 + CP1 task header propagation).
fly secrets set --app pae-platform-worker \
  OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io \
  OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<API_KEY> \
  OTEL_SERVICE_NAME=aicareeros \
  OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production

# pae-platform-beat — Celery beat scheduler. Doesn't itself span
# (beat fires tasks into the queue; the worker spans the
# execution). Setting OTel vars here is harmless and keeps the
# three Celery-side apps configured identically for future
# substrate work that might span beat-scheduled task fires.
fly secrets set --app pae-platform-beat \
  OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io \
  OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=<API_KEY> \
  OTEL_SERVICE_NAME=aicareeros \
  OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production
```

**Each `fly secrets set` triggers an automatic redeploy of the
target app.** Expect ~30-60s downtime per app (Fly does
zero-downtime when min_machines_running ≥ 2; pae-platform runs
at min=1 so the first redeploy has a brief gap). Run during a
low-traffic window if you want to avoid the cold-start spike.

`OTEL_EXPORTER_OTLP_PROTOCOL` is not set — the SDK defaults to
HTTP/protobuf which matches what `OTLPSpanExporter` from the
`opentelemetry-exporter-otlp-proto-http` package speaks. Don't
override it.

---

## METRICS_USERNAME / METRICS_PASSWORD (separate from OTel secrets)

The `/metrics` endpoint requires HTTP Basic auth per the D19.1 CP2
fail-closed contract. Until the OTLPMetricExporter follow-up
ships (see "Auth mismatch resolution" below), the endpoint serves
ad-hoc manual inspection only. Set both secrets so it works
for that purpose:

```bash
# Generate a strong random password for the founder's notes.
fly secrets set --app pae-platform \
  METRICS_USERNAME=metrics_scraper \
  METRICS_PASSWORD="$(openssl rand -base64 24)"
```

Store the password in the founder's secret manager (1Password /
Bitwarden / etc.) so manual `curl` checks work later:

```bash
curl -u "metrics_scraper:<password>" \
  https://pae-platform.fly.dev/metrics
```

The response is Prometheus exposition text with all 15 D-D
canonical metrics. Useful as a sanity check that the backend is
emitting; the Honeycomb traces side is where the actual
production telemetry flows.

---

## Auth mismatch resolution (why no `[metrics]` block in fly.toml)

Fly's managed Prometheus scraper does NOT honor HTTP Basic auth
via `fly.toml` configuration; the `[metrics]` section accepts only
`port` + `path`. Our `/metrics` endpoint requires Basic auth per
D19.1 CP2's fail-closed security contract.

Three options were considered at lock time:

  1. **Remove auth from /metrics entirely.** Declined — leaks the
     metric series (and the internal cardinality) to anyone who
     finds the URL.
  2. **Internal-network detection in the auth gate.** Declined —
     leaks "I am being scraped from inside Fly's network" as a
     bypass primitive; security-discipline regression.
  3. **Route metrics directly to Honeycomb via OTLP**, matching
     the trace path. **Chosen.** Metrics export to Honeycomb's
     `/v1/metrics` endpoint via `OTLPMetricExporter` (same package
     as the trace exporter). Fly's Prometheus stays unscraped; the
     `[metrics]` block in `fly.toml` stays commented out.

The `OTLPMetricExporter` wiring is a small follow-up
(~20 LoC in `app/core/metrics.py` to add the periodic-export
processor, env-var-driven activation, no-op when unset). Tracked
as item in
[`docs/followups/honeycomb-otlp-metrics-export.md`](../followups/honeycomb-otlp-metrics-export.md)
(created alongside this lock).

For the initial lock window, **traces are the load-bearing
telemetry**; metrics serve as an ad-hoc manual debug surface
via curl. Cost-spike alerting via the Honeycomb Trigger pivots on
trace data (sum cost_inr span attributes) and dashboard tables
(via Honeycomb's wide-event queries on trace spans), so the
trace-only initial path covers the D19.2 alert use case.

---

## Verification (founder runs after secrets land)

### Step 1 — Wait 5-10 minutes after the secrets land

Fly redeploys the app on every `fly secrets set`. The new image
has the OTel env vars set; `init_tracing()` reads them at boot
and attaches `OTLPSpanExporter` to the global tracer provider.
First trace spans flush after the next 5-second `BatchSpanProcessor`
flush window. Allow 5-10 minutes margin for the redeploy to
complete + cold-start spans to arrive at Honeycomb.

### Step 2 — Confirm Honeycomb is receiving events

In ui.honeycomb.io:

  1. Navigate to `aicareeros` environment.
  2. Open "Datasets" — there should be a dataset named per the
     `service.name` resource attribute (`aicareeros` per the env
     var set above).
  3. Click the dataset. The "Recent events" pane should show spans
     with `service.name=aicareeros` arriving in real-time.
  4. Run a trivial query: `VISUALIZE COUNT GROUP BY name` over the
     last 10 minutes. Expect at least:
     - `GET /health` spans (Fly health-check fires every 15s)
     - SQLAlchemy query spans (`SELECT`, `INSERT`, etc.)
     - At least one `agent.<name>` span if any chat traffic
       occurred since redeploy

### Step 3 — Confirm a single end-to-end trace

In Honeycomb's trace view (Traces tab):

  1. Filter by `name = agent.<any-agent-name>` (e.g., `agent.career_coach`).
  2. Pick one trace. The trace tree should show:
     - Root: HTTP request span (FastAPI auto-instrumentation)
     - Child: `agent.<name>` (D19.1 CP3 manual instrumentation)
     - Grandchildren: SQLAlchemy spans (auto), httpx spans for
       LLM provider call (auto), Redis spans (auto) if memory
       primitives ran
  3. Span attributes on the `agent.*` span: `agent_id`,
     `agent.model`, `agent.tokens_in`, `agent.tokens_out`,
     `agent.cost_inr`, `agent.outcome`.

If the trace tree is incomplete (e.g., agent span exists but no
SQL children), check the auto-instrumentation logs at boot:
`fly logs -a pae-platform | grep tracing.` — there should be one
log line per instrumentor (`tracing.fastapi_instrumented`,
`tracing.sqlalchemy_instrumented`, etc.).

### Step 4 — Author the cost-spike Trigger

Once Honeycomb is receiving data, follow the procedure at
[`docs/operations/alerts/cost-spike-trigger.md`](alerts/cost-spike-trigger.md)
to author the cost-spike Trigger. The "smoke" step in that doc
(temporarily lower threshold; verify notification arrives)
exercises the end-to-end Honeycomb → email + Slack path.

---

## Rollback procedure

If Honeycomb integration causes issues (rare; the SDK is
no-op-safe and the BatchSpanProcessor flushes async without
blocking the request path), set the endpoint to empty to
silently disable:

```bash
fly secrets set --app pae-platform OTEL_EXPORTER_OTLP_ENDPOINT=""
fly secrets set --app pae-platform-worker OTEL_EXPORTER_OTLP_ENDPOINT=""
fly secrets set --app pae-platform-beat OTEL_EXPORTER_OTLP_ENDPOINT=""
```

The exporter activation is `if endpoint:` per
[`backend/app/core/tracing.py:204`](../../backend/app/core/tracing.py).
Empty string evaluates falsy → no exporter attached → spans
evaporate harmlessly after their trace context closes. Auto-
instrumentation continues to function; the only thing rollback
breaks is "spans visible in Honeycomb." Application behavior is
unaffected.

No code revert needed.

---

## D19.5 gate impact

Once founder confirms verification step 2 (Honeycomb is receiving
events), the D19.5 gate document at
[`docs/architecture/d19-5-pre-launch-readiness-gate.md`](../architecture/d19-5-pre-launch-readiness-gate.md)
moves Section 2 Item 4 from 🔴 RED to 🟢 GREEN.

The other 3 parallel ops items (BUG-CP4, auth-signup-grace, Stripe
webhook) remain unchanged by this lock; they're independent
work surfaces.

---

## Follow-ups created alongside this lock

1. **OTLPMetricExporter wiring** —
   [`docs/followups/honeycomb-otlp-metrics-export.md`](../followups/honeycomb-otlp-metrics-export.md).
   ~20 LoC; flips metrics from "ad-hoc curl" to "live in Honeycomb
   alongside traces." Trigger: when the curl-only metrics workflow
   becomes a friction point (i.e., daily founder review wants
   metric panels in Honeycomb UI alongside traces).
2. **Log shipper to Honeycomb** — not yet registered as a follow-up;
   trigger when cohort-1 incident response needs log queries
   alongside trace queries in one tool. Fly captures stdout; that
   surface is sufficient for cohort-1 review cadence per the
   [Sentry review process](sentry-review-process.md).
