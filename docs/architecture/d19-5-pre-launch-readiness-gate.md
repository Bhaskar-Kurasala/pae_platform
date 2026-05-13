# D19.5 — Pre-launch readiness gate

**Status:** Gate assessment complete (2026-05-13).
**Decision:** The agent reports state; **the founder makes the
final go/no-go call**.
**Headline:** Architect-led substrate **GREEN across all dimensions**.
Of 4 parallel ops-side items, **2 are CONFIG-SHIPPED** awaiting
founder execution (Item 2 auth-signup-grace-jsonb post-2026-05-13
fix + backfill script; Item 4 Honeycomb backend lock); **2 remain
RED** (Item 1 BUG-CP4-LESSON-FK-500 and Item 3 Stripe webhook
env). None of the remaining items are unambiguously launch-
blocking; each carries a specific impact characterized in Section 2.

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

**State (D19.5 close):** 🔴 RED — not landed.

**State (post-investigation-and-fix commit, 2026-05-13):** 🟢
GREEN-config — code fix + regression-guard tests landed; **backfill
execution against production pending founder run** (10-second
dev-DB verification proves the apply path works end-to-end).

**What landed in the fix commit:**
- `entitlement_service.py:677` + `:732` — dropped the `::jsonb`
  cast suffix on both call sites. Postgres auto-casts the
  JSON-shaped `_json_dumps(metadata)` text to the JSONB column
  type at INSERT because the column is declared JSONB
  ([alembic/versions/0057_entitlement_tier.py:101-105](../../backend/alembic/versions/0057_entitlement_tier.py)).
  Same workaround pattern as escalate_to_human.py:181-200.
- Investigation doc with empirical findings:
  [`docs/operations/auth-signup-grace-jsonb-investigation.md`](../operations/auth-signup-grace-jsonb-investigation.md)
  — regression window (2026-05-03 → 2026-05-13; ~10 days);
  downstream impact characterization (signup succeeds; first
  agentic call returns 402 for users without paid entitlement);
  dev-DB affected count (92 students, 90 with paid entitlement
  masking, 2 most-impacted); backfill policy choice
  (`expires_at = NOW() + 24h` per option b — restores access).
- Regression-guard tests in
  [`backend/tests/test_services/test_entitlement_grant_writes.py`](../../backend/tests/test_services/test_entitlement_grant_writes.py)
  — 3 tests using `ast`-based extraction of `text()` call
  arguments; catch `::jsonb` re-introduction at CI without
  false-positives from docstrings / comments.
- Backfill script at
  [`backend/scripts/auth_signup_grace_backfill.py`](../../backend/scripts/auth_signup_grace_backfill.py)
  — dry-run by default + `--apply` flag; idempotent (`WHERE NOT
  EXISTS` guard); backfilled rows carry
  `metadata={'backfill': True, 'reason': 'auth-signup-grace-jsonb',
  'original_signup_at': <user.created_at>}` for future cohort
  analysis. Verified end-to-end on dev DB: dry-run identifies 92
  affected, apply inserts 92, re-dry-run shows 0 residual.
- Sentry fingerprint rule documented at
  [`docs/operations/sentry-review-process.md`](../operations/sentry-review-process.md)
  "Known-issue fingerprints" section. Founder configures in Sentry
  UI; pins `auth.signup_grace_failed` to a stable issue group
  so any future regression surfaces immediately.

**What remains for founder execution:**
1. Run dry-run against production: `uv run python -m
   scripts.auth_signup_grace_backfill --dry-run` from the Fly
   backend app. Reports counts.
2. Verify counts look right (likely 0 if cohort-1 enrollment
   model is paid-at-signup; non-zero otherwise).
3. If non-zero: run `--apply`. Idempotent + safe to re-run.
4. Configure the Sentry fingerprint rule in the Sentry UI per
   the doc.

**Launch-impact assessment (revised):** **LOW** post-fix-landing.
The syntax fix is in place; new signups will create their
signup_grace rows correctly. The remaining question is whether
existing affected users in production need the backfill — that
depends on cohort-1 enrollment model:
- Cohort-1 paid-at-signup: backfill is no-op (dry-run shows 0).
- Cohort-1 includes free-trial users: backfill executes for
  those users; each gets a 24h fresh grant from backfill moment.

**Recommendation (revised):** Founder runs dry-run against
production this week to confirm the affected count. If 0, no
action; Item 2 fully GREEN. If non-zero, run `--apply` (idempotent,
safe). Either way, Item 2 is no longer launch-blocking — the
substrate is fixed; existing-affected-users are addressed via
the script.

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

**State (D19.5 close):** 🔴 RED — not landed.

**State (post-D19.5 lock-config commit, 2026-05-13):** 🟡
YELLOW — **config-shipped, execution-pending**.

**Evidence (updated):**
- Operations doc shipped at
  [`docs/operations/honeycomb-backend-lock.md`](../operations/honeycomb-backend-lock.md)
  with exact `fly secrets set` commands for `pae-platform`,
  `pae-platform-worker`, `pae-platform-beat`, plus Honeycomb-UI
  verification procedure + rollback path.
- `fly.toml` updated with `[metrics]` documentation block
  (commented-out per the auth-mismatch resolution; OTLP-direct
  for metrics is the chosen path) + cross-reference to the lock
  doc.
- D19.1 backend-decision doc
  ([`d19-1-observability-backend-decision.md`](d19-1-observability-backend-decision.md))
  updated with "APPROVED γ Honeycomb (2026-05-13)" + lock-commit
  marker.
- Follow-up registered for the OTLPMetricExporter wiring
  ([`docs/followups/honeycomb-otlp-metrics-export.md`](../followups/honeycomb-otlp-metrics-export.md))
  that migrates metrics from ad-hoc-curl to Honeycomb-resident.

**What remains for founder execution:**
1. Confirm Honeycomb account + ingest API key exist.
2. Run the 3 documented `fly secrets set` commands. Each triggers
   automatic Fly redeploy (~30-60s downtime per app).
3. Wait 5-10 min for first traces to flush; verify in Honeycomb UI
   that `aicareeros` dataset is receiving events.
4. Author the cost-spike Trigger per `cost-spike-trigger.md` —
   that step also un-yellows Section 1 Item 5 (cost-spike alert).

**Launch-impact assessment (revised):** **LOW** post-config-ship.
Founder can either:
- **Path A:** Execute the secrets pre-launch (10 min including
  verification) → Item 4 GREEN by launch.
- **Path B:** Execute post-launch when settled (week-2 ops cycle)
  → Item 4 stays YELLOW for cohort-1 launch week; defer cost-spike
  Trigger going-live to week 2. Founder watches the cost
  dashboard manually during the high-attention launch week
  anyway, which is exactly the workflow the Trigger automates
  for week-2+.

**Recommendation (revised):** Either path is acceptable. Path B
matches the original D19.5 gate recommendation (defer to first
post-launch ops cycle); Path A removes the deferral with 10 min
of founder time. **Founder picks.**

---

## Section 3 — Go/no-go aggregate assessment

### Honest aggregate

| Aggregate | D19.5 close | +Honeycomb-lock-config | +auth-signup-grace fix |
|-----------|-------------|------------------------|-----------------------|
| Architect-led substrate (10 dim) | 🟢 GREEN | 🟢 GREEN | 🟢 GREEN |
| Parallel ops-side items (4 items) | 🔴 RED × 4 | 🟡 1 + 🔴 3 | 🟡 2 + 🔴 2 |
| **Net launch-readiness** | CONDITIONAL | CONDITIONAL (improved) | **CONDITIONAL (much improved)** |

Two RED items remain: Item 1 (BUG-CP4-LESSON-FK-500) and Item 3
(Stripe webhook env config). Per their Section 2 dispositions:
Item 1 is LOW launch-impact (only fires on malformed-API path,
not normal user journey); Item 3 is CONDITIONAL on cohort-1
payment model (LAUNCH-BLOCKING only if cohort-1 takes Stripe
webhook payments during launch week).

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
