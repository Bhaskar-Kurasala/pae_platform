# Sentry review process

D19.2 / CP1.6. The non-paged half of cohort-1 launch operations.
The two D-A alerts (cost spike, uptime) page the founder in real
time; everything else is captured as Sentry events for **periodic
review** rather than real-time paging.

## Cadence

| Stage | Review cadence |
|-------|----------------|
| Cohort-1 launch week | Daily, ~10 minutes |
| Cohort-1 stable (week 2+) | Weekly, ~30 minutes |
| 100+ users | Daily on weekdays, ~15 minutes |
| 200+ users / second engineer | Move to D19.4 (parked) — on-call rotation |

The cadence is calibrated against "do users notice before founder
notices?" At cohort-1 size the founder knows every user by name;
weekly is enough. Bumps to daily during launch week because
brand-new traffic patterns surface novel error classes that
warrant tight feedback.

## What to look for

### 1. Error count trends

Sentry's "Issues" view sorted by count over the last 24h / 7d.
Look for:

- **New issues** (first-seen in the window) — these are regressions
  or newly-exercised code paths. Triage immediately even at low
  count.
- **Spiking issues** (count growing faster than traffic) — these
  are platform regressions or external-dependency issues.
- **High-count low-impact issues** — "this fires 1000x/day but
  no user complains" usually means a noisy log or an over-broad
  exception type. Triage to lower noise OR fix the root cause if
  the noise is masking real bugs.

### 2. New error types

Group by exception type (Sentry calls this "issue type"). Anything
new since last review needs classification:

- **Genuine bug** — code path that should not have raised. Open a
  follow-up; fix in the next code-touch on that area.
- **Flaky external dependency** — LLM provider 503, Anthropic
  rate-limit, Razorpay webhook delay. Monitor the rate; if rate
  is climbing, escalate to the provider or add platform-side
  resilience (retry, circuit breaker, fallback).
- **User-side issue** — malformed input that bypassed validation,
  unsupported browser, network timeout. Usually no action; if
  rate is meaningful, tighten validation or improve error UX.

### 3. Errors correlated to specific user_ids

Sentry groups by `user.id` automatically (D19.1 CP1.2a wires this
via `set_user_context`). A single user generating disproportionate
error volume usually means:

- **Adversarial probing** — tighten that user's
  `daily_cost_ceiling_inr_override` to ₹0 immediately and
  investigate.
- **User-side environment issue** — broken proxy, ad-blocker,
  outdated browser. Reach out via the cohort's support channel.
- **Account-state bug** — something specific to this user's
  data state (corrupt entitlement, race condition in their
  history). Reproduce locally with the user_id; fix.

### 4. Errors with high trace_id collision

Multiple Sentry events sharing a `trace_id` mean one bug is
firing across many request paths or multiple times within one
request. This is usually:

- **A single bad request that fanned out** — rare; the underlying
  call graph is the culprit. Look at the trace in Honeycomb
  (post-backend-lock) for the full picture.
- **Issue-grouping fragmentation** — Sentry's fingerprinting is
  splitting one bug into several issue groups. Configure custom
  fingerprinting for the affected exception type.

## How to triage

For each issue surfaced by review:

| Severity | Action | Latency |
|----------|--------|---------|
| **Genuine bug, user-blocking** | Fix-now: hotfix branch, deploy ASAP | within hours |
| **Genuine bug, recoverable** | Fix-this-week: open issue, schedule | within days |
| **Flaky external** | Monitor: comment on issue, no fix unless rate climbs | weekly review |
| **Known and accepted** | Mark as "known" in Sentry, add to ignore list | one-time |
| **Noise** | Tighten log level / exception type / fingerprinting | within days |

Prefer short comments on the Sentry issue (Sentry threads
investigations naturally) over external notes that drift from
the live state.

## How to investigate

Standard sequence:

1. **Sentry event:** start here. Read the exception, traceback,
   and breadcrumbs. The breadcrumbs are the structlog trail
   leading up to the failure (D19.1 CP1 substrate); they
   usually narrate the failure mode.
2. **Correlation IDs:** every Sentry event carries `trace_id`
   (D19.1 CP3) + `request_id` + `user_id` + `agent_id` (when in
   agent context) per the CP1 substrate. Copy `trace_id`.
3. **Trace view:** in Honeycomb (post-backend-lock), pivot from
   `trace_id` to the full distributed trace. The agent invocation
   span tree shows the call graph; the LLM-call sub-span shows
   token counts + cost; the DB sub-spans show query timings.
4. **Logs:** for non-trace-bound detail, grep production logs by
   `trace_id` (Honeycomb logs view, or `fly logs | grep <trace_id>`
   pre-backend-lock).
5. **Local reproduction:** if the bug is data-state-dependent,
   pull the user's relevant DB rows (anonymize PII first) and
   reproduce against a local stack.

## When to upgrade Sentry tier

Free tier: 5K errors / month, 50 replays, no advanced
fingerprinting controls. Upgrade triggers:

- **Approaching 5K/month:** dashboard's monthly count > 4K.
  Sentry will start dropping events at the cap; we lose
  visibility on the highest-rate issues exactly when triage
  matters most.
- **Issue grouping limits prevent triage:** if many distinct
  bugs share fingerprints (or one bug splits into many), the
  free tier's grouping controls aren't enough. Upgrade to
  Team for custom fingerprinting.
- **Need release tracking:** Free tier supports basic releases;
  Team adds deploy tracking and regression detection. Useful
  post-D19.4 (parked) when deploys are more frequent.

Don't upgrade preemptively. The D-E $0/month target is a
launch-stage discipline; revisit when one of the above triggers.

## Cross-references

- D19.1 Sentry integration: [`backend/app/core/sentry.py`](../../backend/app/core/sentry.py)
- Correlation IDs: [`docs/architecture/d19-1-logging-conventions.md`](../architecture/d19-1-logging-conventions.md)
- Cohort-events review (companion process): [`docs/operations/cohort-events-review-process.md`](cohort-events-review-process.md)
- Deferred alerts (the things NOT being paged): [`docs/followups/d19-deferred-alerting-and-runbooks.md`](../followups/d19-deferred-alerting-and-runbooks.md)
