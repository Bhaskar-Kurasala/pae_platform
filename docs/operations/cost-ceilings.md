# Per-student daily cost ceiling

D19.2 D-B. Application-layer protection against runaway cost burn
from buggy agent loops or adversarial users. Caps individual
student blast radius at `ceiling × user_count`.

## How it works

1. Every agent invocation through `/api/v1/agentic/{flow}/chat`
   resolves an `EntitlementContext` for the student via
   `compute_active_entitlements` (see `app/services/entitlement_service.py`).
2. The context carries `cost_budget_remaining_today_inr` —
   ceiling minus today's accumulated cost.
3. At dispatch entry (`AgenticOrchestratorService.process_request`),
   if `cost_remaining <= 0`, the orchestrator short-circuits with
   a graceful-decline `OrchestratorResult` and records a cohort
   event (`kind="daily_cost_ceiling_hit"`) for founder visibility.
4. The user sees a calm message: "You've reached today's usage
   limit. Please continue tomorrow or contact support if you need
   an exception."
5. No agent invocation, supervisor LLM call, or specialist
   dispatch happens — the cost burn ends here.

## Ceiling resolution order (D-B)

Three layers, top wins:

1. **`users.daily_cost_ceiling_inr_override`** — per-student
   admin lever. Wins unconditionally when non-NULL. Use for
   tightening flagged users (suspected adversarial use, budget
   concerns) or loosening paying customers (one-off allowance)
   without changing global tier configuration.
2. **`course_entitlements.metadata['cost_ceiling_inr_override']`**
   (Pass 3f §H.3) — entitlement-level override. Largest wins
   when multiple entitlements specify overrides. Use for "this
   premium course bought includes a higher daily allowance."
3. **Tier-config default** (`app/core/tiers.py:TIER_CONFIGS`)
   — falls through when neither override is set. Free tier
   ≈ ₹50/day; paid tier defaults are course-config dependent.

## Setting a per-student override

No admin UI shipped at D19.2 (post-D19 scope). Direct SQL:

```sql
-- Tighten a flagged user to ₹0/day (block all agent invocations
-- until the override is removed).
UPDATE users
SET daily_cost_ceiling_inr_override = 0
WHERE id = '<user-uuid>';

-- Loosen a paying customer to ₹500/day for the next 24h
-- (admin reverts after the window closes).
UPDATE users
SET daily_cost_ceiling_inr_override = 500
WHERE id = '<user-uuid>';

-- Remove an override (revert to tier default).
UPDATE users
SET daily_cost_ceiling_inr_override = NULL
WHERE id = '<user-uuid>';
```

## What the user sees when they hit it

Backend response (HTTP 200, `OrchestratorResult`-shape body):

```json
{
  "request_id": "...",
  "conversation_id": "...",
  "response_text": "You've reached today's usage limit. Please continue tomorrow or contact support if you need an exception.",
  "target_agent": null,
  "blocked": true,
  "block_reason": "daily_cost_ceiling_hit",
  "duration_ms": <small>,
  "cost_inr": "0"
}
```

Frontend renders the `response_text` verbatim in the chat surface.
This is distinct from the D-C graceful-failure UX (which is for
*errors*); the ceiling hit is a deliberate, calm, expected
behaviour.

## Mid-flight breach (cost pushed over ceiling during invocation)

The substrate doesn't refund mid-flight work — if a student is
at ₹49/₹50 ceiling and starts an invocation that costs ₹3, the
invocation completes (final cost: ₹52). The next invocation
attempt sees `cost_remaining = -₹2` and is declined.

A `daily_cost_ceiling_breached_during_invocation` log event
(structlog) fires when the post-invocation cost crosses the
ceiling, so the founder sees the breach in the daily Sentry /
log review.

## Monitoring ceiling hits

**Cohort events feed:**

```sql
SELECT occurred_at, actor_handle, label, payload
FROM cohort_events
WHERE kind = 'daily_cost_ceiling_hit'
  AND occurred_at >= NOW() - INTERVAL '24 hours'
ORDER BY occurred_at DESC;
```

A spike of ceiling hits in a short window suggests:
- **Same user repeatedly:** flagged user; consider tightening
  override to ₹0.
- **Many users simultaneously:** the global default is too low
  for organic usage; raise `STUDENT_DAILY_COST_CEILING_INR` env
  or the tier config.
- **Specific agent over-represented in cost burn before hits:**
  agent-side regression; check that agent's prompt + recent
  changes.

## Configuration

| Setting | Default | Tunable via |
|---------|---------|-------------|
| Tier-default ceiling (free) | ~₹50/day | `app/core/tiers.py:TIER_CONFIGS["free"].daily_cost_ceiling_inr` |
| Tier-default ceiling (paid) | varies by course | `app/core/tiers.py:TIER_CONFIGS["paid"].daily_cost_ceiling_inr` |
| Per-student override | NULL (use tier default) | `UPDATE users SET daily_cost_ceiling_inr_override = ?` |

## Cross-references

- Schema: [`backend/alembic/versions/0067_users_daily_cost_ceiling_override.py`](../../backend/alembic/versions/0067_users_daily_cost_ceiling_override.py)
- Resolution helper: [`_resolve_cost_ceiling`](../../backend/app/services/entitlement_service.py)
- Enforcement site: [`AgenticOrchestratorService.process_request`](../../backend/app/services/agentic_orchestrator.py)
- Cost-spike alert: [`docs/operations/alerts/cost-spike-trigger.md`](alerts/cost-spike-trigger.md)
- Cohort-events review process: [`docs/operations/cohort-events-review-process.md`](cohort-events-review-process.md)
