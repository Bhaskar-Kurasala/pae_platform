# D19.1 — Observability substrate overview

**Status:** Substrate sealed at D19.1 CP5 (2026-05-09). Backend
choice (`docs/architecture/d19-1-observability-backend-decision.md`)
pending founder approval; substrate is backend-agnostic and ready
for D19.2 (alerting) consumption once the backend lands.
**Canonical reference for D19.2-D19.5.** Future deliverables in
the launch-operations arc read this first.

D19.1 instrumented the production substrate for cohort-1 launch.
Three pillars (logs / metrics / traces), one dashboard substrate
(JSON-as-code), one substrate-flip discipline arc (CP1 → CP5),
~₹17-23 cumulative cost.

## Executive summary

| Pillar | Substrate | Source-of-truth module |
|---|---|---|
| **Logs** | structlog with W3C-compatible correlation IDs (`request_id`, `trace_id`, `user_id`, `agent_id`); Celery propagation via `CorrelatedTask`; sampling processor (deterministic per `trace_id`). | [`app/core/logging.py`](../../backend/app/core/logging.py), [`app/core/request_id.py`](../../backend/app/core/request_id.py), [`app/core/celery_logging.py`](../../backend/app/core/celery_logging.py), [`app/core/log_sampling.py`](../../backend/app/core/log_sampling.py) |
| **Metrics** | `prometheus_client`-backed; 15 D-D canonical metrics (api / agent / db / celery / auth + agent-internal); D-C cardinality discipline + D-D naming linter; auth-gated `/metrics` scrape endpoint. | [`app/core/metrics.py`](../../backend/app/core/metrics.py), [`app/core/metrics_middleware.py`](../../backend/app/core/metrics_middleware.py), [`app/api/v1/routes/metrics.py`](../../backend/app/api/v1/routes/metrics.py) |
| **Traces** | OpenTelemetry SDK with W3C trace context propagator; auto-instrumentation (FastAPI / SQLAlchemy / Redis / httpx / requests / Celery); manual span per agent invocation; head-based `ParentBased(TraceIdRatioBased)` sampler; privacy denylist at the substrate boundary. | [`app/core/tracing.py`](../../backend/app/core/tracing.py) |
| **Dashboards** | 6 dashboards as backend-agnostic JSON; per-dashboard owner per D-F; runbook scaffolds in [`docs/operations/runbooks.md`](../operations/runbooks.md); CI discipline tests validate metric refs + runbook anchors. | [`docs/operations/dashboards/`](../operations/dashboards/) |

## Locked architectural decisions (D19.1 prompt)

The CP1-CP5 arc honours these locked decisions verbatim. They are
canonical until D19.2+ proposes amendments backed by
empirical evidence.

  * **D-A — Three pillars, separate but correlated.** Logs answer
    "what exactly happened?"; metrics answer "how often, what trend?";
    traces answer "where in the call graph?". Conflating them
    produces a substrate that does none well.
  * **D-B — Correlation IDs are non-negotiable.** Every log line,
    metric label set (where cardinality-safe), and trace span
    must carry the IDs that let the three pillars correlate.
    Specifically: `trace_id` (W3C 32-hex, derived from the request's
    UUID4 bytes), `request_id` (UUID4 string for human grep),
    `user_id` (when authenticated), `agent_id` (when in agent
    invocation). `session_id` and `cohort_id` are reserved for
    future binding (cohort schema modeling deferred — see
    "Open D-G items" below).
  * **D-C — Cardinality discipline.** Metric labels never include
    `user_id`, `session_id`, `trace_id`, `email`, `ip_address`,
    `full_name`, `cohort_id`, etc. Hard constraint at the metric
    registration layer (see Pattern 35 evidence). Per-event /
    per-user identifiers live in logs (CP1 contextvars) and trace
    span attributes (CP3 — but only ID-shaped attributes there too;
    payload contents and PII are denylisted at span level too).
  * **D-D — Naming convention.** `aicareeros_<component>_<measurement>[_<unit>]`.
    Component values: `api | agent | db | auth | celery | gateway | billing`.
    Durations in `_seconds` (Prometheus convention); bytes in
    `_bytes`; rupees in `_inr`; counts omit unit. Enforced at
    registration time; rejected names raise `MetricRegistrationError`
    at boot.
  * **D-E — Sampling strategy.** Logs: 100% retention for ERROR /
    WARNING; INFO / DEBUG sampled deterministically per `trace_id`
    (env-tunable `LOG_SAMPLE_INFO_RATE` / `LOG_SAMPLE_DEBUG_RATE`).
    Metrics: 100% retention (aggregated, not sampled). Traces:
    head-based 1% baseline shipped; tail-based "include errors +
    p99 latency" deferred to backend collector (e.g., Honeycomb
    Refinery if backend choice lands as γ).
  * **D-F — Dashboard ownership model.** Each of the 6 dashboards
    has exactly one named owner. Unowned dashboards are deleted,
    not maintained.
  * **D-G — Backend choice deferred to closure.** D19.1 CP5
    delivered the recommendation
    ([`d19-1-observability-backend-decision.md`](d19-1-observability-backend-decision.md));
    founder approval is the gating step. The substrate ships
    against pluggable backends — switching backends post-approval
    is a destination URL change, not a code rewrite.

## CP-by-CP substrate inventory

### CP1 — Logs

**Correlation ID emission:**
  * `RequestIDMiddleware` ([`app/core/request_id.py`](../../backend/app/core/request_id.py))
    binds `request_id` (UUID4) and `trace_id` (32-hex; derived
    from same UUID bytes) to structlog contextvars at request
    entry. Defensive read of W3C `traceparent` header — full
    propagation came in CP3.
  * `get_current_user` / `get_current_user_optional`
    ([`app/core/security.py`](../../backend/app/core/security.py))
    bind `user_id` after auth resolves successfully.
  * `BaseAgent.run` ([`app/agents/base_agent.py`](../../backend/app/agents/base_agent.py))
    binds `agent_id` at canonical entry; covers all 20 agents
    via the shared harness.
  * `CorrelatedTask` ([`app/core/celery_logging.py`](../../backend/app/core/celery_logging.py))
    auto-injects current contextvars into Celery task headers at
    enqueue; `task_prerun` / `task_postrun` signal handlers
    restore / clear context inside the worker. Both `.delay()`
    and `.apply_async()` ride this without call-site changes.
    Beat-scheduled / CLI tasks mint a fresh `trace_id` with
    `trace_origin='task'`.

**Sampling:**
  * `sampling_processor` ([`app/core/log_sampling.py`](../../backend/app/core/log_sampling.py))
    drops INFO / DEBUG events probabilistically; ERROR / WARNING
    always retained. Decision is `BLAKE2b(trace_id) < rate` for
    deterministic-per-trace consistency; random fallback when no
    `trace_id` is bound (boot, scheduler init).

**Convention reference:** [`docs/architecture/d19-1-logging-conventions.md`](d19-1-logging-conventions.md).

### CP2 — Metrics

**The 15 D-D canonical metrics:**

| Metric (Prometheus name) | Type | Labels | Emission site |
|---|---|---|---|
| `aicareeros_api_requests` | Counter | endpoint, method, status_code | `MetricsMiddleware` |
| `aicareeros_api_request_duration_seconds` | Histogram | endpoint, method | `MetricsMiddleware` |
| `aicareeros_agent_invocations` | Counter | agent_id, outcome | `BaseAgent.run` |
| `aicareeros_agent_invocation_duration_seconds` | Histogram | agent_id | `BaseAgent.run` |
| `aicareeros_agent_cost_inr` | Counter | agent_id | `BaseAgent.log_action` + `AgenticBaseAgent._finalize_action_log` |
| `aicareeros_db_pool_connections_in_use` | Gauge | (none) | SQLAlchemy `checkout` / `checkin` events |
| `aicareeros_db_query_duration_seconds` | Histogram | query_type | SQLAlchemy `before_cursor_execute` / `after_cursor_execute` |
| `aicareeros_celery_tasks` | Counter | task_name, outcome | `task_postrun` signal in `celery_logging.py` |
| `aicareeros_auth_events` | Counter | event_type | `auth_service.AuthService._record_auth_event` |
| `aicareeros_agent_eval_score` | Histogram | agent_id | `evaluation.py` (legacy shim re-export) |
| `aicareeros_agent_tool_call_duration_seconds` | Histogram | tool, status | `tools.py` (via ms→s adapter) |
| `aicareeros_agent_memory_recall_hits` | Counter | mode | `memory.py` |
| `aicareeros_agent_memory_recall_duration_seconds` | Histogram | mode | `memory.py` (via ms→s adapter) |
| `aicareeros_agent_memory_writes` | Counter | scope | `memory.py` |
| `aicareeros_agent_inter_agent_call_depth` | Histogram | (none) | `communication.py` |

**Registration discipline:**
  * `register_counter` / `register_histogram` / `register_gauge`
    ([`app/core/metrics.py`](../../backend/app/core/metrics.py))
    enforce D-D naming + D-C cardinality at construction time.
    Failure → `MetricRegistrationError` at boot.
  * Discipline tests in
    [`backend/tests/test_core/test_d19_cp2_metrics_discipline.py`](../../backend/tests/test_core/test_d19_cp2_metrics_discipline.py)
    walk REGISTRY post-hoc as a CI safety net.

**Scrape endpoint:** `/metrics` (root level) with HTTP Basic auth
gated by `METRICS_USERNAME` / `METRICS_PASSWORD`. Fail-closed
(503) when env vars unset; constant-time credential comparison.

### CP3 — Traces

**OpenTelemetry SDK configured in
[`app/core/tracing.py`](../../backend/app/core/tracing.py):**
  * `init_tracing()` builds `TracerProvider` with W3C trace
    context propagator (default), head-based
    `ParentBased(TraceIdRatioBased(rate))` sampler tuned via
    `OTEL_TRACES_SAMPLER_ARG` (default 0.01).
  * Pluggable OTLP/HTTP exporter — active when
    `OTEL_EXPORTER_OTLP_ENDPOINT` is set; no-op otherwise. CP5
    backend choice flips this on.
  * Auto-instrumentation: FastAPI, SQLAlchemy, Redis, httpx,
    requests (in `instrument_auto`); Celery (in
    `instrument_celery`).

**Manual span per agent invocation:**
  * `BaseAgent.run` wraps the agent invocation in `agent.<name>`
    span with attributes: `agent_id`, `agent.model`,
    `agent.outcome`, `agent.duration_ms`, `agent.tokens_in`,
    `agent.tokens_out`.
  * `AgenticBaseAgent.execute` wraps in `agent.<name>` span;
    `_finalize_action_log` annotates the active span with
    `agent.cost_inr`, `agent.tokens_total`,
    `agent.model_resolved`.

**Privacy denylist:** `set_safe_span_attribute` rejects 24 keys
(PII / payload / secret) at the substrate boundary;
`SpanAttributeError` raised. Discipline tests at
[`backend/tests/test_core/test_d19_cp3_tracing_discipline.py`](../../backend/tests/test_core/test_d19_cp3_tracing_discipline.py).

### CP4 — Dashboards

**Six dashboards** in [`docs/operations/dashboards/`](../operations/dashboards/),
each with named owner per D-F:

| Dashboard | Owner | Time-range | Purpose |
|---|---|---|---|
| api-health.json | engineering | 1h | Request rate, error rate, p50/p95/p99 latency by endpoint |
| agent-health.json | engineering | 1h | Per-agent invocations, error rate, latency, top-10 slowest, eval score, inter-agent depth |
| cost.json | founder + ops | 24h | Cost rate by agent, cumulative today/week/month, top burners |
| db-health.json | engineering | 1h | Pool gauge, query rate, p95 latency by type, slow-query rate |
| auth-events.json | ops | 24h | Signup, login, login-failure, signup-conflict rates |
| operational.json | engineering | 24h | Celery rate/success/error/retry, memory recall+write, tool-call p95 |

**Schema:** documented in
[`docs/operations/dashboards/README.md`](../operations/dashboards/README.md).
Backend-agnostic — backends get a thin transformer at backend-lock
time per the migration path in
[`d19-1-observability-backend-decision.md`](d19-1-observability-backend-decision.md).

**CI discipline:** dashboard files validated against the running
REGISTRY; runbook anchors validated against
[`runbooks.md`](../operations/runbooks.md). Tests in
[`backend/tests/test_core/test_d19_cp4_dashboards.py`](../../backend/tests/test_core/test_d19_cp4_dashboards.py)
catch metric-name drift + runbook link rot at CI time.

## Pillar-mapping reference (which pillar answers which question shape)

CP4 institutional learning. The three pillars are not
interchangeable; each answers a different question shape, and a
question taken to the wrong pillar produces a wrong-shape
answer.

| Question shape | Best pillar | Reason |
|---|---|---|
| "How often did X happen in window W?" | **Metrics** | Aggregated counters / rates. Cheap to compute over long windows. Trade-off: bounded label cardinality. |
| "What was the trend of X over W weeks?" | **Metrics** | Same. Time-series storage is the metric backend's strength. |
| "What exactly happened during incident I?" | **Logs** | Per-event detail. Filterable by correlation IDs (CP1 substrate). Trade-off: query cost grows with retention. |
| "What did user U do in their last session?" | **Logs** | `user_id` contextvar (CP1.2a) plus structured event names. Trade-off: doesn't aggregate well. |
| "Where did latency / error originate in this request's call graph?" | **Traces** | Per-request span tree. Trade-off: sampled by default; rare events under-represented unless tail-sampling is active. |
| "Was X correlated with Y at the same wall-clock?" | **Traces** (or wide-event store like Honeycomb) | Cross-pillar correlation; conventional metrics+logs require manual eye-balling. |

**Anti-patterns:**
  * "Per-user-cost dashboard" via metric label `user_id` — D-C
    violation. Solution: cost lives in metrics aggregated by
    `agent_id`; per-user attribution lives in logs (`user_id`
    contextvar) or traces (span attributes). Cohort attribution
    lives in `mv_student_daily_cost` and the `agent_invocation_log`
    DB table; metrics are the high-level aggregate, not the
    per-user truth.
  * "Did this exact user hit this exact endpoint?" via metrics —
    same. Logs answer this; metrics tell you the rate. The
    `auth-events` dashboard surfaces this gap explicitly in its
    `notes` array.

## How to extend

### Adding a new metric

1. In `app/core/metrics.py`, call `register_counter` /
   `register_histogram` / `register_gauge` at module level. The
   helper validates D-D naming + D-C cardinality at registration
   time; a malformed registration crashes import (fail fast).
2. Emit at the canonical chokepoint for the metric's
   component. Helper-level emission (a function in the same
   module) is preferred over scattered `.labels(...).inc()`
   calls — Pattern 35 enforcement.
3. Add to the per-component dashboard if the metric is
   incident-grade (alert source) or trend-grade (review source).
   Discipline tests at CI catch the metric-reference resolution.

### Adding a new log line

Per [`d19-1-logging-conventions.md`](d19-1-logging-conventions.md):
use `structlog.get_logger()` at module top; snake-dot event
names (`agent.run.start`); structured kwargs only; never PII or
LLM payload contents. Sentry breadcrumb bridge picks every log
line up; PII discipline at structlog layer is load-bearing for
Sentry's PII discipline.

### Adding a trace span

For request-path / DB / Redis / outbound HTTP: nothing to do.
Auto-instrumentation covers the boundary.

For agent-internal spans: nest inside the existing `agent.<name>`
span via `tracer.start_as_current_span(...)`. Use
`set_safe_span_attribute(span, key, value)` not
`span.set_attribute` — the privacy denylist gates the substrate
boundary.

### Adding a dashboard

Add a new JSON file to `docs/operations/dashboards/` matching
the schema in [`README.md`](../operations/dashboards/README.md).
Add a section to [`runbooks.md`](../operations/runbooks.md)
matching the dashboard's `runbook` anchor field. Update the
discipline test's expected dashboard set
([`test_dashboard_directory_has_six_dashboards`](../../backend/tests/test_core/test_d19_cp4_dashboards.py)).

### Adding an alert (D19.2 preview)

Pick a panel from a CP4 dashboard. Author a Trigger / Monitor /
Alert in the chosen backend's alerting surface (Honeycomb
Triggers / Datadog Monitors / Grafana Alerting) referencing the
panel's query. Update the dashboard's runbook section in
`runbooks.md` with the alert threshold + response procedure.

## Open D-G items registered for D19.2-D19.5

  * **Backend lock.** Founder approval gate; see
    [`d19-1-observability-backend-decision.md`](d19-1-observability-backend-decision.md).
  * **Tail-based sampling.** D-E specifies "errors + p99 latency
    100% retain"; CP3 ships head-based 1% only. Tail-sampling is
    a backend-collector decision (e.g., Honeycomb Refinery).
    Lands at backend-lock time.
  * **`cohort_id` schema modeling.** D-B reserves `cohort_id` as
    a load-bearing correlation ID; the User model has no
    `cohort_id` foreign key and no membership table exists.
    Affects D19.3 per-cohort cost attribution. Three remediation
    options registered (FK on User / derived view / level_slug
    proxy); decision deferred to when D19.3 needs it. CP1's
    `_PROPAGATED_KEYS` reservation is in place — substrate is
    ready.
  * **Production sampling tuning.** CP1 INFO retention defaults
    to 100% for cohort-1 launch; D-E target is 10% steady-state.
    Empirical-trigger transition: lower `LOG_SAMPLE_INFO_RATE`
    once D19.2 alerting surfaces volume-based justification.
  * **Real-LLM batch flake cluster.** CP3 closure surfaced two
    additional Phase B test flakes (career_coach +
    resume_reviewer) in addition to the supervisor over-length
    flake registered at CP2. Combined remediation in
    [`docs/followups/cp3-traceability-supervisor-flake.md`](../followups/cp3-traceability-supervisor-flake.md):
    A (prompt tightening) + B (boundary truncation) + C
    (supervisor `_track_llm_usage` gap) + suite-mode OTel
    sampler override. Pre-launch micro-deliverable.
  * **`auth.signup_grace_failed` SQL bug.** Surfaced in backend
    logs during CP3 verification: `INSERT INTO free_tier_grants
    ... VALUES (..., :meta::jsonb)` — Postgres rejects the
    `:meta::jsonb` parameter binding shape. Best-effort path
    swallows; signup_grace silently fails. Separate from D19.x;
    register as bug-fix-team scope.

## Pattern catalog updates from D19.1

Ratified at CP5 in
[`docs/followups/migration-verification-discipline.md`](../followups/migration-verification-discipline.md):

  * **Pattern 22** — bidirectional value clause's evidence base
    extended with 4 D19.1 instances (CP1 conformance discovery,
    CP2 shim recognition, CP3 absence verification, CP5
    catalog-itself drift). N=18+ across D18+D19.1.
  * **Pattern 35 NEW** — Infrastructure-layer auto-propagation.
    Convention drift across consumers is a predictable failure
    mode; enforce at the convention-definition site
    (decorator / base class / helper / registration wrapper).
    N=4 within D19.1: CP1 `CorrelatedTask`, CP2 `register_*`
    helpers, CP3 `set_safe_span_attribute`, CP4 dashboard
    schema validation.
  * **Closure-time test verification discipline** — registered
    as canonical sub-rule. Closure reports run tests in the
    canonical environment; static review supplementary, not
    substitutive. Scope-matching refinement: substrate code
    changes → full integration suite; docs / tests / schema
    changes only → discipline tests.
  * **Pattern 36 NEW** — Prospective convention enforcement at
    substrate boundaries. Anticipate convention enforcement
    even when the enforcement layer can't yet be built. ~5%
    authoring overhead prevents proportional retrofit cost.
    Validated at CP2 against the 2024-era `metrics.py` shim;
    18 consumers flipped with zero call-site edits.

## D19.2 readiness assessment (CP5.5)

D19.2 will author alerting rules. This section verifies that
each likely D19.2 alert has a backing data stream in the D19.1
substrate. Gaps that aren't addressable in D19.1 are explicitly
registered as D19.2 first-deliverable scope.

| Likely alert | Backing substrate | Readiness |
|---|---|---|
| **API 5xx error rate > N/min** | `aicareeros_api_requests` counter, `status_code` label | ✅ Ready. Query: rate over `status_code=~"5.."`. Panel exists in `api-health.json`. |
| **API endpoint p95 latency > T seconds** | `aicareeros_api_request_duration_seconds` histogram | ✅ Ready. Panel `p95-latency-by-endpoint`. |
| **Agent error rate by agent_id > N/min** | `aicareeros_agent_invocations` counter, `outcome` label | ✅ Ready. Panel `error-rate-by-agent` in `agent-health.json`. |
| **Agent p95 invocation duration > T seconds** | `aicareeros_agent_invocation_duration_seconds` histogram | ✅ Ready. Panel `p95-latency-by-agent`. |
| **Cost spike: cost_inr in last 1h > threshold** | `aicareeros_agent_cost_inr` counter | ✅ Ready. Panel `cost-rate-by-agent` in `cost.json`. Alert is `rate(...[1h])` against agent-grouped sum. |
| **Daily cost ceiling approached: cumulative > 80% of cap** | `aicareeros_agent_cost_inr` counter | ✅ Ready. Panel `cumulative-cost-today`. Per-student attribution lives in `mv_student_daily_cost`; metric is the platform-aggregate signal. |
| **DB pool saturation: connections_in_use > 0.8 × max** | `aicareeros_db_pool_connections_in_use` gauge | ✅ Ready. Panel `pool-connections-in-use` in `db-health.json`. Threshold = 0.8 × (db_pool_size + db_max_overflow) = 0.8 × 30 = 24. |
| **Slow query rate spike** | `aicareeros_db_query_duration_seconds` histogram (>0.5s buckets) | ✅ Ready. Panel `slow-query-count`. Cross-reference with `slow_query` structlog warnings for SQL-text detail. |
| **Login failure rate / login rate > 5%** | `aicareeros_auth_events` counter | ✅ Ready. Panel `login-failure-rate` + `login-rate` ratio in `auth-events.json`. |
| **Celery task error rate > N/5min** | `aicareeros_celery_tasks` counter, `outcome` label | ✅ Ready. Panel `celery-error-rate` in `operational.json`. |
| **Celery task retry rate spike** | `aicareeros_celery_tasks` counter, `outcome="retry"` | ✅ Ready. Panel `celery-retry-rate`. |
| **Provider rate-limit hits detected** | structlog event `agent.run.error` with `error_type="rate_limit"` | ⚠ **Gap — D19.2 first-deliverable scope.** Metric pillar can't bound the cardinality of `error_type` cleanly without a denylist exception. The right shape is a log-query alert (Honeycomb Triggers / Datadog Logs Monitor / Grafana Loki alert) on the `agent.run.error` event filtered by `error_type` (which is a log-attribute, never a metric label per D-C). The dashboard placeholder note in `operational.json` flags this. |
| **Batch flakiness: rate-limit retry vs contract failure split** | structlog `agent.run.error` events grouped by `error_type` | ⚠ **Gap — D19.2 first-deliverable scope** (same mechanism as above). The "is this a transient retry-class error or a contract-class error" question lives in logs/traces, not metrics. Documented in `operational.json` notes. |
| **Service availability / health endpoint flap** | `/health` endpoint already exists; not currently covered by a metric | ⚠ **Minor gap — easily closed in D19.2.** D19.2 can author a synthetic-probe alert (Honeycomb Heartbeat / Datadog Synthetics / Grafana uptime check) hitting `/health` directly; substrate doesn't need to change. |
| **Sentry exception rate** | Sentry's own dashboard | ✅ Out-of-scope for D19.1 substrate. Sentry already alerts on its own ingest rate; D19.2 can either consume Sentry alerts directly or layer a synthetic on top of `sentry.capture_exception` calls visible in logs. |

**Coverage summary:** of ~14 likely D19.2 alerts, **11 are
directly metric-backed** by D19.1 CP2 substrate; **2 require
log-query alerting** (provider rate-limit + flakiness split —
D-C cardinality discipline forbids the metric-label shape
that would otherwise close them); **1 is a synthetic-probe
alert** (health endpoint, easy in D19.2). The 2 log-query
gaps are the right shape for D19.2 first-deliverable scope —
they can't be closed with a different metric design (would
violate D-C), so authoring log-query alerts in the chosen
backend is the structurally correct path.

**Recommendation for D19.2 authoring order:**

1. Wire the 11 metric-backed alerts first (low-risk; backing
   data is already flowing).
2. Author the 2 log-query alerts next (depends on backend
   choice; e.g., Honeycomb Triggers natively support
   `event_name = "agent.run.error" AND error_type CONTAINS
   "rate_limit"`).
3. Close the synthetic-probe gap last (out-of-band; no
   substrate dependency).

## D19.2 build-out (cross-reference, added at D19.2 closure 2026-05-09)

D19.2 reshaped the original D19.2-D19.5 launch-operations arc to
match cohort-1 economic reality. D19.1's substrate underpins
everything D19.2 ships; D19.2 itself adds:

  * **Two paged alerts** (D19.2 D-A) — cost spike (Honeycomb
    Trigger; gated on backend lock) + uptime (UptimeRobot free
    tier). All other alerts deferred per
    [`docs/followups/d19-deferred-alerting-and-runbooks.md`](../followups/d19-deferred-alerting-and-runbooks.md).
  * **Per-student daily cost ceiling** (D19.2 D-B) — application-
    layer protection enforcing at agentic dispatch entry. New
    `users.daily_cost_ceiling_inr_override` column wins over tier
    defaults per
    [`docs/operations/cost-ceilings.md`](../operations/cost-ceilings.md).
  * **Graceful-failure UX** (D19.2 D-C) — backend exception
    handler envelope extended with `trace_id` + `user_message`
    fields; new inline `GracefulFailureMessage` frontend
    component for non-route failures (chat, mock interview,
    practice, capstone surfaces).
  * **Operational review processes** (D19.2 / CP1.6) —
    [`sentry-review-process.md`](../operations/sentry-review-process.md)
    and
    [`cohort-events-review-process.md`](../operations/cohort-events-review-process.md)
    document the non-paged half of cohort-1 launch ops.
  * **D19.4 parked** (D19.2 D-D) — on-call rotation, escalation
    paths, full runbook discipline deferred until second engineer
    OR cohort >200 users. The CP4 runbook scaffold remains as
    "first-look + correlate" pointers; no further population at
    this stage.

The cross-reference goes both ways:

  * **D19.1 → D19.2:** D19.2's cost ceiling consumes
    `_compute_today_cost_inr` from D19.1's existing matview
    aggregation (`mv_student_daily_cost`); enforcement at
    `AgenticOrchestratorService.process_request` consumes the
    `EntitlementContext.cost_budget_remaining_today_inr` field
    populated by `compute_active_entitlements`. D19.2's
    graceful-failure UX consumes D19.1's `trace_id` contextvar
    bound by `RequestIDMiddleware` for correlation.
  * **D19.2 → D19.1:** D19.2 surfaced no new pattern candidates
    (consumption of D19.1 substrate, not new architectural
    pattern territory) — confirms the per-arc discipline that
    consumption arcs don't expand the pattern catalog.

## Cross-references

- Saved D19.1 prompt: [`docs/claude-code-prompts/d19-1-prompt.md`](../claude-code-prompts/d19-1-prompt.md)
- Logging conventions: [`docs/architecture/d19-1-logging-conventions.md`](d19-1-logging-conventions.md)
- Backend decision: [`docs/architecture/d19-1-observability-backend-decision.md`](d19-1-observability-backend-decision.md)
- Dashboards: [`docs/operations/dashboards/`](../operations/dashboards/)
- Runbooks: [`docs/operations/runbooks.md`](../operations/runbooks.md)
- Pattern catalog: [`docs/followups/migration-verification-discipline.md`](../followups/migration-verification-discipline.md)
- D18 Phase A overview (cross-referenced with D19.1 substrate): [`docs/architecture/d18-phase-a-test-infrastructure-overview.md`](d18-phase-a-test-infrastructure-overview.md)
- Real-LLM batch flake follow-up: [`docs/followups/cp3-traceability-supervisor-flake.md`](../followups/cp3-traceability-supervisor-flake.md)
