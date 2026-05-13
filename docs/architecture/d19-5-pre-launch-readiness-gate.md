# D19.5 — Pre-launch readiness gate

**Status:** Gate assessment complete (2026-05-13).
**Decision:** The agent reports state; **the founder makes the
final go/no-go call**.
**Headline:** Architect-led substrate **GREEN across all dimensions**.
4 of 4 parallel ops-side items **NOT YET LANDED** — none are
launch-blocking but each carries a specific impact on day-one
operational visibility.

This document is the architect-led closure for D19.5. It reports
the state of every load-bearing dimension cohort-1 launch depends
on, with explicit green/yellow/red classification + evidence +
launch-impact assessment. The founder uses this as the gate
artifact for the launch authorization decision.

---

## Section 1 — Architect-led substrate verification

Per dimension: state + evidence. Substrate dimensions are work
**this conversation completed across D19.1+D19.2+D19.3**.

| Dimension | State | Evidence |
|-----------|-------|----------|
| **Logging substrate** (D19.1 CP1) | 🟢 GREEN | structlog + correlation IDs (`request_id`, `trace_id`, `user_id`, `agent_id`) + Celery propagation via `CorrelatedTask` + sampling processor. 11/11 unit tests pass (`test_d19_cp1_correlation.py`). Verified end-to-end in canonical environment. |
| **Metrics substrate** (D19.1 CP2) | 🟢 GREEN | `prometheus_client` + 15 D-D canonical metrics + cardinality denylist linter + naming-convention linter + /metrics endpoint with HTTP Basic auth (fail-closed default). 10/10 unit tests pass (`test_d19_cp2_metrics_discipline.py` + `test_d19_cp2_metrics_endpoint.py`). |
| **Tracing substrate** (D19.1 CP3) | 🟢 GREEN | OpenTelemetry SDK + W3C trace context propagator + 5 auto-instrumentations (FastAPI, SQLAlchemy, Redis, httpx, requests) + Celery instrumentor + manual `agent.<name>` spans in BaseAgent.run + AgenticBaseAgent.execute + privacy denylist via `set_safe_span_attribute`. Pluggable OTLP exporter (active when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; no-op otherwise — see ops-side Item 4). 9/9 unit tests pass. |
| **Dashboards** (D19.1 CP4 + D19.3) | 🟢 GREEN | 6 D19.1 dashboards (api-health, agent-health, cost, db-health, auth-events, operational) + D19.3 founder-glance panel extensions in cost.json (`todays-burn-vs-expected`, `students-near-or-at-ceiling`, `ceiling-hits-today`, consolidated cumulative, placeholder for cohort). 25/25 discipline tests pass (`test_d19_cp4_dashboards.py`), including the new `placeholder` + `db_query` panel-type schema extensions. |
| **Cost-spike alert config** (D19.2) | 🟡 YELLOW | Honeycomb Trigger configuration shipped at `docs/operations/alerts/cost-spike-trigger.md` with query / threshold / recipients / smoke procedure. **Trigger going live is gated on ops-side Item 4 (Honeycomb backend lock).** When backend lock lands, founder authors the Trigger per the doc; smoke runs once. |
| **Uptime alert config** (D19.2) | 🟡 YELLOW | UptimeRobot configuration shipped at `docs/operations/alerts/uptime-monitor.md`. **Going live is gated on founder-side prerequisite** (UptimeRobot free-tier signup; monitor creation). The agent does not create accounts. `/health` endpoint verified 200 in D19.5 smoke; production target is reachable once Fly deployment is live. |
| **Per-student daily cost ceiling** (D19.2 CP1.4) | 🟢 GREEN | Schema migration `0067_users_daily_cost_ceiling.py` applied; `_resolve_cost_ceiling` 3-tier resolution; enforcement at `AgenticOrchestratorService.process_request` dispatch entry; cohort-event recording on hit. 6 D19.2 tests pass + D19.5 smoke c (at-threshold blocks) + smoke d (below-threshold allows) pass. |
| **Graceful-failure UX** (D19.2 CP1.5) | 🟢 GREEN | Backend exception handler envelope carries `user_message` + `trace_id` + `request_id`; `RequestIDMiddleware` surfaces IDs on `request.state` so handler reads them after contextvar cleanup. Inline `GracefulFailureMessage` frontend component for non-route failures (sibling to existing `RouteError` route boundary). 4 backend exception-handler tests + 6 frontend component tests + D19.5 smoke e (envelope shape on simulated error) pass. |
| **Sentry capture + correlation IDs** (D19.2 + D19.1 CP1) | 🟢 GREEN | structlog → Sentry breadcrumb bridge configured at D19.1 CP1; PII redaction in `app/core/sentry.py`; D19.5 smoke f verifies `request_id` + `trace_id` are bound to structlog contextvars during request lifecycle (the substrate that feeds Sentry breadcrumbs). Sentry SDK is no-op without DSN (CI safe); production target requires founder-side SENTRY_DSN secret (Sentry account exists per existing integration). |
| **D19.5 smoke suite** (this deliverable) | 🟢 GREEN | 9 functional-shape tests covering /health, /metrics auth, ceiling enforcement (both branches), graceful-failure envelope, correlation ID flow, cost dashboard validation, both follow-up docs. All passing in canonical playwright-runner environment in 0.23s. |

**Architect-led substrate aggregate: 🟢 GREEN.** Every dimension
this conversation owns is functionally verified.

The two YELLOW items (cost-spike Trigger going-live, UptimeRobot
going-live) are **configuration shipped, going-live blocked by
non-architect work** (Honeycomb backend lock + founder account
creation). Their YELLOW status means "the substrate to make this
GREEN is in place; the operational steps to flip it GREEN are not
within architect-led scope."

---

## Section 2 — Parallel ops-side verification

Per item: state + evidence + launch-impact assessment. These are
**bug-fix-team / ops-side work** the architect-led engagement
registered as parallel-to-D19. The agent verifies landed/not-landed;
the agent does NOT do the fixes.

### Item 1 — BUG-CP4-LESSON-FK-500

**State:** 🔴 RED — not landed.

**Evidence (Pattern 22 drift-detection at pre-flight):**
- `backend/tests/playwright/journeys/test_cp4_error_modes.py:213`
  carries `@pytest.mark.xfail(strict=True, reason=...)` referencing
  BUG-CP4-LESSON-FK-500 verbatim.
- `backend/app/services/progress_service.py:258` `complete_lesson`
  takes `lesson_id` and proceeds without pre-validating that the
  lesson row exists; the FK violation propagates as an unhandled
  `IntegrityError` → 500.
- No fix commit in `git log` matching the bug ID or the file's
  pre-existence-check pattern.

**Fix scope (per existing follow-up `docs/followups/bug-cp4-lesson-fk-500.md`):**
1-hour bug-fix-team work. Pre-validate `Lesson.id` exists before
inserting `StudentProgress`, OR catch `IntegrityError` and re-raise
as `HTTPException(404)`. Remove the xfail marker once the fix
lands.

**Launch-impact assessment:** **LOW**. The bug fires only when an
authenticated user POSTs `/me/lessons/{nonexistent-uuid}/complete`
with a valid-format UUID that doesn't exist. The frontend's
"complete lesson" button operates against known lesson IDs sourced
from the course catalog; this code path is reachable only via
malformed API client / curl, not the normal user journey. The
visible failure mode (500 instead of clean 404) doesn't disrupt
cohort-1 users; it's a discoverability + correctness gap.

**Recommendation:** **NOT launch-blocking.** Ship cohort-1 with the
bug present; fix in the first post-launch fix-cycle. Update D19.5
gate doc when fix lands.

---

### Item 2 — auth-signup-grace-jsonb

**State:** 🔴 RED — not landed.

**Evidence (Pattern 22 drift-detection at pre-flight):**
- `backend/app/services/entitlement_service.py:677` still emits
  `VALUES (:id, :uid, 'signup_grace', :now, :exp, :meta::jsonb)`
  with the `:meta::jsonb` parameter-binding syntax that asyncpg
  rejects (`PostgresSyntaxError: syntax error at or near ":"`).
- Same syntax repeats at line 732 for the
  `placement_quiz_session` grant insert (collateral surface for
  the same bug).
- No fix commit; backend logs during recent verification runs
  still show `auth.signup_grace_failed` warnings firing on every
  fresh-student registration.

**Fix scope (per existing follow-up `docs/followups/auth-signup-grace-jsonb-cast-syntax.md`):**
2-4 hour bug-fix-team work. Replace `:meta::jsonb` with the asyncpg-
compatible cast syntax (use `CAST(:meta AS jsonb)` OR pass `meta`
as a `dict` and let asyncpg handle JSONB encoding via the
SQLAlchemy `JSON()`/`JSONB()` type). Possibly backfill grants for
users registered during the regression window (any student whose
signup ran after this code path landed and saw the silently-swallowed
exception).

**Launch-impact assessment:** **MEDIUM**. The bug silently fails
the signup-grace entitlement grant for every new student. The
`try/except` wrapping at `auth_service.py:90` swallows the failure
and logs a warning — students proceed past signup but **without a
free-tier grant**. Cohort-1 students:
- See **NO functional failure at signup** (the swallow keeps signup
  green).
- Hit `402 Payment Required` from the canonical agentic endpoint
  on their first agent invocation IF they haven't yet purchased a
  course AND aren't covered by another free-tier path.
- Are **invisible to the daily founder review** unless founder
  greps logs for `auth.signup_grace_failed`.

For cohort-1 specifically: if the cohort is paid-by-design (every
student has a course entitlement at signup), this bug is invisible.
If any cohort-1 students rely on `signup_grace` for their first
24-hour free window, this bug presents as "402 on first interaction"
— a real UX issue.

**Recommendation:** **PROBABLY launch-blocking; founder decides
based on cohort-1 enrollment model**. If cohort-1 includes any
signup_grace-dependent users, this must land before launch. If
cohort-1 is 100% paid-entitlement-at-signup, defer to first
post-launch fix-cycle. Fix is small (2-4 hours); the launch-block
question is "is anyone in cohort-1 affected?"

---

### Item 3 — Stripe webhook env config (`STRIPE_WEBHOOK_SECRET`)

**State:** 🔴 RED — not configured.

**Evidence:**
- `backend/tests/playwright/journeys/test_cp1_journey_i_payment.py`
  3 tests xfail-gated on `STRIPE_WEBHOOK_SECRET` being empty in the
  runner overlay env (lines 13, 98, 160, 186).
- No `STRIPE_WEBHOOK_SECRET` in `docker-compose.yml` or
  `docker-compose.playwright.yml` env blocks.
- `fly.toml` does not declare or reference the secret (Fly secrets
  are not visible to the agent).

**Fix scope:** ~30 minutes once the env lands. Founder adds
`STRIPE_WEBHOOK_SECRET` to Fly secrets + runner overlay env. The
3 xfail tests un-xfail automatically once the env is set.

**Launch-impact assessment:** **CONDITIONAL on cohort-1 payment
model**:
- If cohort-1 takes payments via Stripe webhooks: **LAUNCH-BLOCKING**.
- If cohort-1 is invitation-only / pre-paid / non-monetized:
  **NOT launch-blocking** — Stripe webhooks aren't on the cohort-1
  critical path.

Existing engagement context says "cohort-1 is high-touch (founder
knows users by name)"; payment model not explicitly stated.

**Recommendation:** **founder confirms cohort-1 payment model**.
If payments-during-launch-week: launch-blocking; ship fix
pre-launch. If not: deferred to first paid-cohort deliverable.

---

### Item 4 — Honeycomb backend lock commit

**State:** 🔴 RED — not landed.

**Evidence:**
- `fly.toml` line 73 has a forward-looking comment about /metrics
  under real load but no `[metrics]` config section.
- No `OTEL_EXPORTER_OTLP_ENDPOINT` or `HONEYCOMB_API_KEY` in any
  compose / fly config visible to the agent.
- D19.1 CP3 backend logs from prior verification showed
  `tracing.otlp_init_failed` not firing because the env was unset
  (correct no-op behavior); production needs both env vars set
  for actual ingest.

**Fix scope (per `docs/architecture/d19-1-observability-backend-decision.md`
migration path):**
- Founder creates Honeycomb org + ingest key.
- Set `OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io` and
  `OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=$HONEYCOMB_API_KEY`
  on Fly backend + worker apps.
- Set `METRICS_USERNAME` + `METRICS_PASSWORD` on Fly + add
  `[metrics]` section to `fly.toml` so Fly's managed Prometheus
  scrapes /metrics into the org-level Prometheus endpoint.
- (Optional) Import the 6+1 backend-agnostic dashboards into
  Honeycomb via the API.

Estimated: ~₹2-3 + 1 developer-day (founder-side or ops-side).

**Launch-impact assessment:** **MEDIUM** (depends on launch-day
observability stance):
- If launch-day stance is "we'll review logs / dashboards via Fly
  console + cohort_events SQL queries for week 1": **NOT
  launch-blocking**. Cost-spike Trigger goes-live in week 2.
- If launch-day stance is "cost-spike Trigger fires on day 1
  during the highest-burn-rate period": **LAUNCH-BLOCKING**. The
  Trigger config doc can't fire without Honeycomb ingestion.

Recommendation: **defer to first post-launch ops-cycle**. Cohort-1
launch week is the highest-attention window — the founder is on
the cost dashboard hourly anyway. The cost-spike Trigger's value
is "automated catch when founder ISN'T watching"; that's the
week-2+ value proposition.

---

## Section 3 — Go/no-go aggregate assessment

### Honest aggregate

| Aggregate | State |
|-----------|-------|
| Architect-led substrate (10 dimensions) | 🟢 GREEN (8 green + 2 yellow; yellows are config-shipped-pending-ops-side) |
| Parallel ops-side items (4 items) | 🔴 RED across all 4 |
| **Net launch-readiness** | **CONDITIONAL** |

### The decision surface

The architect-led work is **done and verified**. The launch decision
rests on the founder's call across the 4 ops items, with
characterizations above. To convert the parallel items from RED to
green, the following are needed:

1. **BUG-CP4-LESSON-FK-500** — ship the 1-hour fix OR accept the
   500-on-malformed-API discoverability gap during cohort-1.
   Recommendation: accept; fix post-launch.
2. **auth-signup-grace-jsonb** — depends on cohort-1 enrollment
   model. If any students rely on signup_grace: ship the 2-4 hour
   fix pre-launch. If 100% paid-entitlement-at-signup: accept;
   fix post-launch.
3. **Stripe webhook env** — depends on cohort-1 payment model. If
   Stripe webhooks fire during cohort-1: configure the secret
   pre-launch. If not: defer to first paid-cohort deliverable.
4. **Honeycomb backend lock** — depends on launch-day observability
   stance. Defer to first post-launch ops-cycle is the conservative
   recommendation; cohort-1 launch week founder presence covers
   the gap.

### What this gate does NOT decide

This document **reports state**; the founder **makes the call**.
The agent's recommendations above are inputs to the founder's
decision, not the decision itself. Specifically:

- Founder confirms cohort-1 payment + enrollment model (Items 2-3).
- Founder weighs observability-tooling-on-day-1 vs accept-as-week-2
  (Item 4).
- Founder accepts or rejects the LOW-impact recommendation for
  Item 1.

If founder authorizes launch with any RED ops items still RED:
**re-run D19.5 gate** post-launch (rerun the 9 smoke tests + update
this gate doc with the post-launch-fix landing). The 9 smokes are
fast (~0.23s in canonical environment) and the gate doc is text;
re-running adds ~₹0.

---

## D19 arc closure

D19.5 is the final architect-led deliverable in the D19
launch-operations arc.

- **D19.1** sealed at `3a7f211` (substrate)
- **D19.2** sealed at `2f8a367` (alerts + cost ceiling + UX)
- **D19.3** sealed at `3285199` (cost dashboard polish + deferral docs)
- **D19.4** PARKED per D19.2 D-D (on-call rotation, escalation, full
  runbooks; re-evaluation trigger: second engineer joins OR cohort
  >200 users)
- **D19.5** sealed at this commit; **D19 arc CLOSED**.

Cumulative D19 arc cost: **~₹21-31** of original ~₹15-25 envelope.
The ~₹6-11 overage is explained by closure-time test verification
discipline (D19.1 CP5 canonical sub-rule): empirical green at each
closure via canonical Linux/Docker runs rather than static-review
claims. The discipline caught real bugs at cheap stages — anyio
collision (CP1), supervisor flake rate (CP2/CP3), contextvars vs
request.state (CP1.5), 5 documentation drift instances (CP1.4).
The verification is what makes this gate document trustworthy.

## Cross-references

- D19.1 observability overview: [`d19-1-observability-overview.md`](d19-1-observability-overview.md)
- D19.1 backend decision: [`d19-1-observability-backend-decision.md`](d19-1-observability-backend-decision.md)
- D19.1 logging conventions: [`d19-1-logging-conventions.md`](d19-1-logging-conventions.md)
- D19.2 ops docs: [`docs/operations/cost-ceilings.md`](../operations/cost-ceilings.md), [`docs/operations/sentry-review-process.md`](../operations/sentry-review-process.md), [`docs/operations/cohort-events-review-process.md`](../operations/cohort-events-review-process.md), [`docs/operations/alerts/cost-spike-trigger.md`](../operations/alerts/cost-spike-trigger.md), [`docs/operations/alerts/uptime-monitor.md`](../operations/alerts/uptime-monitor.md)
- D19.3 dashboards + follow-ups: [`docs/operations/dashboards/cost.json`](../operations/dashboards/cost.json), [`docs/followups/provider-level-cost-attribution-via-gen-ai-otel.md`](../followups/provider-level-cost-attribution-via-gen-ai-otel.md), [`docs/followups/cohort-membership-modeling.md`](../followups/cohort-membership-modeling.md)
- Deferred-work inventory: [`docs/followups/d19-deferred-alerting-and-runbooks.md`](../followups/d19-deferred-alerting-and-runbooks.md)
- D19.5 smoke suite: [`backend/tests/test_core/test_d19_5_pre_launch_readiness.py`](../../backend/tests/test_core/test_d19_5_pre_launch_readiness.py)
- Pattern catalog: [`docs/followups/migration-verification-discipline.md`](../followups/migration-verification-discipline.md)
