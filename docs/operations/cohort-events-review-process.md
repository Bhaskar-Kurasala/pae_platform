# Cohort-events review process

D19.2 / CP1.6 companion to the Sentry review process. Where Sentry
captures *errors*, the `cohort_events` table captures
*operationally interesting normal events*: signups, role
transitions, ceiling hits, payment events, capstone submissions.

## Cadence

Same shape as the Sentry review:

| Stage | Cadence |
|-------|---------|
| Cohort-1 launch week | Daily, ~5 minutes |
| Cohort-1 stable (week 2+) | Weekly, ~15 minutes |
| 100+ users | Daily on weekdays, ~10 minutes |

## Daily query

```sql
-- Events in the last 24h grouped by kind, ordered by count.
SELECT
  kind,
  COUNT(*) AS event_count,
  MIN(occurred_at) AS first_seen,
  MAX(occurred_at) AS last_seen
FROM cohort_events
WHERE occurred_at >= NOW() - INTERVAL '24 hours'
GROUP BY kind
ORDER BY event_count DESC;
```

A glance at the per-kind counts surfaces:

- **Spikes** — kind X jumped from 5/day to 200/day. Investigate.
- **Drops** — kind Y was steady at 20/day, now 0. Either traffic
  changed or the event-emitting code path regressed.
- **New kinds** — never-seen-before kind. Confirm intentional
  (a new event_type was added in a recent commit) vs. unintentional
  (typo, taxonomy drift).

## What to investigate when each event_type spikes

| Event kind | Spike means | First investigation step |
|------------|-------------|--------------------------|
| `signup` | Marketing campaign landed; or signup-page bug allowing many test accounts | Check `cohort_events.actor_handle` distribution — same handle repeating = bot/automation; spread of handles = organic |
| `level_up` | Cohort just crossed a promotion gate together (group cohort effect); or gate logic regressed | Check `level_slug` payload + `users.promoted_at` timestamps |
| `daily_cost_ceiling_hit` | Same user hitting ceiling repeatedly (adversarial); OR many users hitting (global default too low) | Per-user count of hits in the last 24h; if same user >10x, tighten override |
| `daily_cost_ceiling_breached_during_invocation` | An invocation pushed a user over ceiling mid-flight; rare but worth knowing | Inspect `payload` for the agent + cost involved; if frequent, tighten that agent's prompt to control cost variance |
| `signup_grace_failed` | Race or DB schema bug (existing followup `auth-signup-grace-jsonb-cast-syntax.md`); freshly-signed-up users may be mis-onboarded | Cross-check Sentry for the matching `auth.signup_grace_failed` warnings |

## When to add a new event_kind

Add a new `kind` to `cohort_events` when:

- **A new operational concern emerges** that needs founder-level
  visibility but isn't an error (so Sentry isn't the right
  surface).
- **An existing process needs auditability** that's currently
  invisible (e.g., when an admin override is set; when a refund
  is processed).
- **An aggregate signal would benefit a future dashboard** —
  cohort_events is the natural feed for the trend-shape
  dashboards that don't fit metric pillar (D-C cardinality
  discipline forbids per-user labels).

The discipline: keep `kind` values finite and snake_case. The
diagnostic-clarity ranking depends on stable enum-shape kinds.
Drift surfaces as the daily review's "new kinds" investigation
finding it hasn't seen before.

## How to add a new event_kind

1. Pick a snake_case name. Document what it represents.
2. Find the code path that's the canonical emit site. Add:
   ```python
   from app.services.cohort_event_service import record_event

   await record_event(
       db,
       kind="your_new_kind",
       actor=user,  # or None for system-initiated events
       label="Human-readable single-line description",
       payload={"key": "structured data for later analysis"},
   )
   ```
3. Update this doc's "What to investigate when each event_type
   spikes" table with the new kind + first-investigation step.

## Per-user view

```sql
-- Recent events for a specific user (the "what has this user been
-- up to today?" investigation).
SELECT occurred_at, kind, label, payload
FROM cohort_events
WHERE actor_id = '<user-uuid>'
  AND occurred_at >= NOW() - INTERVAL '7 days'
ORDER BY occurred_at DESC
LIMIT 50;
```

Useful when a Sentry event surfaces a specific `user_id` and you
want the cohort-event timeline for context. Sentry breadcrumbs
narrate the request that failed; cohort_events narrate the user's
journey leading up to it.

## Cross-references

- Schema: [`backend/app/models/cohort_event.py`](../../backend/app/models/cohort_event.py)
- Helper: [`backend/app/services/cohort_event_service.py`](../../backend/app/services/cohort_event_service.py)
- Sentry review (companion): [`docs/operations/sentry-review-process.md`](sentry-review-process.md)
- Cost ceilings (the kind that fires `daily_cost_ceiling_hit`): [`docs/operations/cost-ceilings.md`](cost-ceilings.md)
