# D19.x deferred alerting + parked D19.4

**Status:** Open. Tracked-not-blocking.
**Origin:** D19.2 closure (2026-05-09). Reshaped scope per founder
direction; original D19.2-D19.5 launch-operations arc reduced to
match cohort-1 economic reality (20-100 users, solo on-call,
$0/month tooling budget, "try again" failure UX acceptable).

**Update (D19.3 closure, 2026-05-13):** D19.3 shipped the cost-
tracking dashboard refinements (founder-glance panels in
`docs/operations/dashboards/cost.json`). Two cost-tracking
follow-ups landed as separate deferral docs with their own
re-evaluation triggers:
  * [`provider-level-cost-attribution-via-gen-ai-otel.md`](provider-level-cost-attribution-via-gen-ai-otel.md)
    — per-LLM-provider / per-model-version / per-token-class
    attribution; trigger: Anthropic gen_ai conventions reach stable.
  * [`cohort-membership-modeling.md`](cohort-membership-modeling.md)
    — per-cohort attribution; trigger: cohort-2 onboarding planning,
    corporate cohort commitment, or cohort-1 retrospective question.

D19.3 added no items to the deferred-alerts table below; the
table is unchanged. The dashboard refinement was the only D19.3
substrate work and it shipped, not deferred.

## What this is

D19.2 shipped two alerts (cost spike, uptime) and the per-student
cost ceiling. The original D19.2 prompt's coverage map listed ~14
likely alerts; the reshaped scope deliberately defers ~12 of them
to the post-revenue stage. Plus all of D19.4 (on-call rotations,
escalation paths, runbooks) is parked entirely.

This doc is the inventory of what's deferred and the trigger
conditions that bring each item back into scope.

## Deferred alerts (visualized in dashboards but not paged)

The dashboards from D19.1 CP4 already render these signals; the
founder reviews them manually during the weekly operational pass.
Paging them in real time isn't justified at cohort-1 scale where
user reports surface bugs within hours.

| Alert | Backing data stream | Why deferred | Re-evaluation trigger |
|-------|---------------------|--------------|----------------------|
| API endpoint p95 latency > T | `aicareeros_api_request_duration_seconds` | Latency drifts hours-to-days; founder catches via weekly dashboard pass | Cohort >100 users OR p95 baseline drift detected |
| API 5xx error rate > N/min | `aicareeros_api_requests` (status_code=5..) | Same; user reports come faster than alert thresholds at this scale | Same |
| Agent error rate by agent_id > N/min | `aicareeros_agent_invocations` (outcome=error) | Per-agent regression; founder catches via Sentry weekly review | Cohort >100 users OR new agent ships |
| Agent p95 invocation duration > T | `aicareeros_agent_invocation_duration_seconds` | Latency drift; weekly | Cohort >100 users |
| DB pool saturation > 0.8 × max | `aicareeros_db_pool_connections_in_use` gauge | Pool exhaustion would cascade to outage → uptime alert (D-A 2) catches it | Cohort >200 users (pool resize threshold) |
| Slow query rate spike | `aicareeros_db_query_duration_seconds` (>0.5s) | Slow queries logged via structlog `slow_query` warning; founder reviews logs/Sentry | Cohort >100 users |
| Login failure rate / login rate > 5% | `aicareeros_auth_events` (event_type=login_failure / login) | Brute-force attempts at cohort-1 scale visible in cohort-events review | Public-facing signup OR login automation detected |
| Celery task error rate > N/5min | `aicareeros_celery_tasks` (outcome=error) | Async failures non-user-facing; weekly review | Async work becomes user-blocking (e.g., exam scoring on async path) |
| Celery task retry rate spike | `aicareeros_celery_tasks` (outcome=retry) | Same; transient downstream issues self-resolve | Same |
| Provider rate-limit detected | structlog `agent.run.error` (error_type=rate_limit) | Log-query alert shape; founder catches in Sentry | Anthropic/MiniMax rate-limit hits >5x/day OR cohort >100 |
| Memory recall hit rate drop | `aicareeros_agent_memory_recall_hits` (rate) | Embeddings drift / DB index issue; weekly | Recall metric drops below baseline-mean − 1 stddev |
| Eval score median drop | `aicareeros_agent_eval_score` (median) | Quality regression; weekly review of agent dashboard | Median drops >10% from baseline |

Every item carries the same shape: backing data is **already
flowing** through D19.1 substrate; the dashboard panel **already
exists** in CP4; the absent piece is the alert / paging
configuration. Re-enabling any one of these is hours of work
post-trigger, not days.

## Parked entirely (D19.4 territory)

These are not deferred-but-tracked; they're parked-with-no-active-roadmap
until cohort scale, engineering team size, or operational pain
crosses a threshold:

| Item | Why parked | Re-evaluation trigger |
|------|------------|----------------------|
| On-call rotation | Solo on-call (founder); rotation-of-one is overhead | Second engineer joins |
| Escalation paths | Same — no one to escalate to | Second engineer joins |
| Detailed runbooks (full discipline) | Documentation-for-one is overhead with zero process value | Second engineer joins OR cohort >200 users |
| PagerDuty / Opsgenie integration | Free tiers exist but solo on-call doesn't need paging discipline | Second engineer OR after-hours operations become routine |
| Status page (public) | Cohort-1 users have direct channel to founder; manual comms suffice | Cohort >100 users OR paid-tier launch |
| Scheduled disaster-recovery drills | DR procedures exist (Fly.io managed Postgres + backups); rehearsal cost outweighs payoff at cohort-1 | Paid-tier launch OR cohort >500 users |

## Re-evaluation triggers (consolidated)

The triggers across the table above cluster around four
thresholds:

1. **Second engineer joins the team** → unblocks D19.4
   (on-call rotation, escalation, full runbooks).
2. **Cohort exceeds 100 users** → re-evaluate the latency / error
   rate alerts. User reports stop surfacing all bugs at this
   scale; alerting starts paying back its cost.
3. **Cohort exceeds 200 users** → re-evaluate DB pool, capacity
   alerts, status page.
4. **Monthly Sentry error count exceeds 5K** → upgrade Sentry
   tier (per `sentry-review-process.md`), and that's a natural
   moment to also re-evaluate the deferred alerts.

When any trigger fires, this doc is the authoritative inventory of
what to revisit. The next architect-led pass picks the items that
match the trigger and authors the alert configuration; the
backing data is already flowing, so authoring time is bounded.

## What's NOT in scope for re-evaluation

Things deliberately omitted from the revisit list:

- **Refactoring the D19.1 substrate.** D19.1 is sealed. Any new
  alert authored in a D19.x post-revenue pass consumes the
  existing substrate without touching it.
- **Switching observability backends.** D19.1 CP5 documented the
  reversibility cost (1-2 dev-days) and the trigger conditions
  for switching. Backend choice isn't part of "re-enable deferred
  alerts" work.
- **Adding a paid-tier observability product.** D-E $0/month
  target persists until revenue justifies. Don't pre-commit to a
  paid tier in anticipation of growth.

## Cross-references

- D19.1 substrate overview: [`docs/architecture/d19-1-observability-overview.md`](../architecture/d19-1-observability-overview.md)
- D19.1 backend decision: [`docs/architecture/d19-1-observability-backend-decision.md`](../architecture/d19-1-observability-backend-decision.md)
- D19.2 alerts shipped: [`docs/operations/alerts/cost-spike-trigger.md`](../operations/alerts/cost-spike-trigger.md), [`docs/operations/alerts/uptime-monitor.md`](../operations/alerts/uptime-monitor.md)
- D19.2 cost ceiling: [`docs/operations/cost-ceilings.md`](../operations/cost-ceilings.md)
- D19.2 review processes: [`docs/operations/sentry-review-process.md`](../operations/sentry-review-process.md), [`docs/operations/cohort-events-review-process.md`](../operations/cohort-events-review-process.md)
- Dashboards (D19.1 CP4): [`docs/operations/dashboards/`](../operations/dashboards/)
