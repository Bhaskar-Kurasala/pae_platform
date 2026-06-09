---
title: Pass 3f — Entitlement Enforcement Layer
status: Final — implementation contract for the Pass 2 H1 fix and per-tier access model
date: After Pass 3e sign-off, before D9 implementation
authored_by: Architect Claude (Opus 4.7)
purpose: Close the Pass 2 H1 finding (agents are completely ungated by entitlements). Define the architectural placement of entitlement checks, the per-tier access model, cost ceiling configuration, free-tier policy, refund-revocation propagation, edge cases, and monitoring. Sets the contract for D9's entitlement gating implementation.
supersedes: nothing
superseded_by: nothing — this is the canonical entitlement design
informs: D9 (the foundational entitlement gating ships here), every subsequent agent migration (each agent declares its tier requirements)
implemented_by: D9 (primary), with refinements possible in D10–D17 as edge cases surface
depends_on: D1 (course_entitlements table schema), Pass 3b §6.1 (the three-layer enforcement sketch), Pass 3c (per-agent capabilities), Pass 3d (entitlement-related tools)
---

# Pass 3f — Entitlement Enforcement Layer

> Pass 2 found that agents are completely ungated by entitlements. Any logged-in user can invoke any agent regardless of payment status. This is the launch-blocker fix from Pass 2's hypothesis 1.

> Pass 3b sketched the three-layer enforcement model (route gate, Supervisor gate, dispatch gate). This pass nails down each layer's exact contract, defines the tier infrastructure (with one tier shipped in v1), specifies the free-tier policy, handles the edge cases (refunds, expirations, admin-on-behalf-of), and defines the monitoring.

---

## Section A — The Three-Layer Enforcement Model

Defense in depth. Each layer catches different failure modes. Removing any one is fine in theory, fragile in practice.

### A.1 Layer 1 — Route-level dependency (the outermost gate)

The canonical agentic endpoint at `POST /api/v1/agentic/{flow}/chat` declares an entitlement requirement via FastAPI dependency:

```python
# backend/app/api/v1/dependencies/entitlement.py

from fastapi import Depends, HTTPException, status
from app.api.v1.dependencies.auth import get_current_user
from app.services.entitlement_service import compute_active_entitlements
from app.models.user import User

async def require_active_entitlement(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EntitlementContext:
    """
    Returns EntitlementContext if the user has at least one active entitlement
    OR is within the free-tier window. Raises 402 Payment Required otherwise.

    EntitlementContext is consumed by the orchestrator to populate
    SupervisorContext.entitlements (Pass 3b §3.1).
    """
    ctx = await compute_active_entitlements(session, user.id)

    if ctx.is_empty():
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error_code": "no_active_entitlement",
                "message": (
                    "Your AICareerOS subscription has expired or you haven't "
                    "purchased a course yet. Browse available courses to continue."
                ),
                "next_action": "browse_catalog",
                "next_url": "/catalog",
            },
        )

    return ctx
```

The `EntitlementContext` is the structured representation of "what this user can access right now." It feeds Layers 2 and 3.

```python
class EntitlementContext(BaseModel):
    user_id: UUID
    active_entitlements: list[ActiveEntitlement]   # paid courses + bundles
    free_tier: FreeTierState | None                # if applicable
    effective_tier: Literal["free", "standard"]    # for cost-ceiling lookup
    cost_budget_remaining_today_inr: Decimal
    cost_budget_used_today_inr: Decimal
    rate_limit_state: RateLimitState

    def is_empty(self) -> bool:
        return not self.active_entitlements and self.free_tier is None

    def can_invoke(self, agent_capability: AgentCapability) -> tuple[bool, str | None]:
        """Used by Layer 2 and 3. Returns (allowed, reason_if_denied)."""
        if not agent_capability.requires_entitlement:
            return (True, None)
        if self.active_entitlements:
            return (True, None)
        if self.free_tier and agent_capability.name in self.free_tier.allowed_agents:
            return (True, None)
        return (False, "agent_not_in_tier")
```

### A.2 Layer 2 — Supervisor's reasoning gate

The Supervisor receives `entitlements` and `cost_budget_remaining_today_inr` in `SupervisorContext` (per Pass 3b §3.1). Its prompt is constructed to make refusal the only valid output when entitlements are insufficient or budget is exhausted.

The Supervisor does NOT re-decide whether the user is entitled in general — Layer 1 already let them through. It decides whether the *specific* agent they're trying to reach is in their tier:

```
[Inside the supervisor prompt, hard constraints section]

You MUST decline with action="decline" and decline_reason="entitlement_required" if:
- The student requested an agent in available_agents that is NOT marked
  available_now (this happens when the user's tier doesn't include that agent
  or when the agent is rate-limited).

You MUST decline with action="decline" and decline_reason="cost_exhausted" if:
- The student's cost_budget_remaining_today_inr is below 1.0 INR AND the
  primary intent requires a specialist call (i.e., not a billing question
  or simple clarification you can resolve via the supervisor's reasoning alone).
```

The Supervisor's output is structured (`RouteDecision` per Pass 3b §3.2) so Layer 3 can validate the decision before dispatching.

### A.3 Layer 3 — Dispatch-time validation

Between the Supervisor's decision and the actual specialist call, the dispatch layer (Pass 3b §5) re-checks entitlement state. This catches:

- **Entitlement revoked between Supervisor decision and dispatch** (refund processed mid-request, fraud hold applied, account suspended)
- **Free-tier window expired between Supervisor decision and dispatch** (student is at the boundary of their 24-hour window)
- **Cost ceiling crossed mid-chain** (Step 1 used more than expected, Step 2 would push over budget)

```python
# Inside the dispatch layer
async def dispatch_single(decision: RouteDecision, ctx: SupervisorContext) -> AgentResult:
    # Re-check entitlement state (race-window protection)
    fresh_ctx = await compute_active_entitlements(session, ctx.student_id)
    target_capability = registry.get_capability(decision.target_agent)

    allowed, reason = fresh_ctx.can_invoke(target_capability)
    if not allowed:
        return _decline_response(reason, decision.target_agent)

    # Cost-budget check (small budget for the call)
    if fresh_ctx.cost_budget_remaining_today_inr < target_capability.typical_cost_inr:
        return _decline_response("cost_exhausted", decision.target_agent)

    # Proceed with dispatch
    return await _execute_dispatch(decision, ctx, fresh_ctx)
```

The fresh re-check is cheap (one cache lookup or one indexed query) and rare to fire — most requests pass cleanly. When it does fire, it's catching exactly the race condition that would otherwise produce a "you got billed for an agent call after your refund" complaint.

### A.4 Why three layers

| Layer | Catches | Cost |
|---|---|---|
| Route (Layer 1) | Unauthenticated access, fully unentitled users, expired subs | One indexed DB query, ~5ms |
| Supervisor (Layer 2) | Wrong-tier requests, cost-exhausted requests with graceful messaging | Already in the LLM call's context |
| Dispatch (Layer 3) | Race conditions, mid-chain budget exhaustion | One cache lookup, ~1ms |

Removing Layer 1 means agents become probe-able by anyone with a JWT. Removing Layer 2 means rejections look like raw 402s instead of friendly "you can't afford this right now" messaging. Removing Layer 3 means refunds and cost ceilings have race windows.

Three layers, kept in sync via the shared `EntitlementContext` data structure.

---

## Section B — Tier Infrastructure (One Tier in v1)

Multi-tier-ready infrastructure, single tier shipped. Adding `premium` later is a config change, not an architecture change.

### B.1 Schema additions

The existing `course_entitlements` table from D1 gets a `tier` column:

```sql
-- Migration 0057_entitlement_tier.py

ALTER TABLE course_entitlements
ADD COLUMN tier TEXT NOT NULL DEFAULT 'standard'
CHECK (tier IN ('free', 'standard', 'premium'));

CREATE INDEX idx_entitlements_user_tier ON course_entitlements (user_id, tier)
WHERE revoked_at IS NULL;
```

The `'premium'` value is allowed by the CHECK constraint but no entitlements are created with it in v1. When premium ships, no schema change is needed.

### B.2 Tier configuration

Tiers are defined in code, not a database table. Configuration lives at `backend/app/core/tiers.py`:

```python
from decimal import Decimal
from pydantic import BaseModel

class TierConfig(BaseModel):
    name: str
    allowed_agents: set[str] | Literal["*"]      # specific agents or all
    daily_cost_ceiling_inr: Decimal
    burst_rate_limit_per_minute: int
    hourly_rate_limit_per_hour: int
    upgrade_path: str | None = None              # what tier to suggest upgrading to

TIER_CONFIGS: dict[str, TierConfig] = {
    "free": TierConfig(
        name="free",
        allowed_agents={
            # Onboarding / placement only
            "billing_support",       # always free; questions about your account
            "supervisor",            # the orchestrator itself; routes free-tier requests
            # Placement-quiz-specific agents (added when those flows are wired):
            # "placement_quiz_agent",  # if extracted as a separate agent
        },
        daily_cost_ceiling_inr=Decimal("5.00"),
        burst_rate_limit_per_minute=3,
        hourly_rate_limit_per_hour=20,
        upgrade_path="standard",
    ),
    "standard": TierConfig(
        name="standard",
        allowed_agents="*",          # all agents reachable per Pass 3a Addendum roster
        daily_cost_ceiling_inr=Decimal("50.00"),
        burst_rate_limit_per_minute=10,
        hourly_rate_limit_per_hour=100,
        upgrade_path=None,
    ),
    # "premium": TierConfig(...)    # not shipped in v1
}

DEFAULT_TIER = "standard"
```

Why in code rather than DB:

- Changes are reviewed via PR (config drift becomes visible in git history)
- No "the prod tier table got out of sync with staging" failure mode
- Tier configs rarely change; making them dynamic adds complexity for no benefit
- Per-student overrides (rare, e.g., comp'd accounts) live in `course_entitlements.metadata` and are explicit

### B.3 Capability gating per tier

The `AgentCapability` (Pass 3b §3.1, Pass 3c §C) gets a new field:

```python
class AgentCapability(BaseModel):
    name: str
    description: str
    # ... existing fields ...
    requires_entitlement: bool                   # already exists in Pass 3b
    minimum_tier: Literal["free", "standard", "premium"] = "standard"  # NEW
    # ... rest ...
```

The Supervisor's `available_agents` list (built dynamically per Pass 3b §3.1) filters by:

```python
def filter_capabilities_for_user(
    all_capabilities: list[AgentCapability],
    entitlement_ctx: EntitlementContext,
) -> list[AgentCapability]:
    tier = entitlement_ctx.effective_tier
    config = TIER_CONFIGS[tier]

    available = []
    for cap in all_capabilities:
        # Tier check: the user's tier must meet the agent's minimum
        if not _tier_meets_minimum(tier, cap.minimum_tier):
            continue
        # Allow-list check (free tier has explicit allow-list)
        if config.allowed_agents != "*" and cap.name not in config.allowed_agents:
            continue
        # available_now check (rate limits, cost ceilings, dependency health)
        if not cap.available_now:
            continue
        available.append(cap)
    return available


def _tier_meets_minimum(user_tier: str, required_tier: str) -> bool:
    tier_order = ["free", "standard", "premium"]
    return tier_order.index(user_tier) >= tier_order.index(required_tier)
```

Result: free-tier users only see free-tier-allowed agents in the Supervisor's prompt. They cannot even know the others exist via this surface.

### B.4 Per-agent tier defaults (per Pass 3a Addendum)

Default tier for the v1 roster:

| Agent | minimum_tier | Rationale |
|---|---|---|
| `learning_coach` | `standard` | Heart of paid product |
| `mcq_factory` | `standard` | Used inside paid quiz flows |
| `senior_engineer` | `standard` | Heaviest LLM cost; gated |
| `project_evaluator` | `standard` | Capstone evaluator; paid feature |
| `practice_curator` | `standard` | NEW; paid feature |
| `career_coach` | `standard` | Paid feature |
| `study_planner` | `standard` | NEW; paid feature |
| `resume_reviewer` | `standard` | Paid feature |
| `tailored_resume` | `standard` | Paid feature |
| `mock_interview` | `standard` | Paid feature |
| `content_ingestion` | `standard` | Background only; not student-facing; tier doesn't really apply |
| `progress_report` | `standard` | Background; sent to paid students |
| `portfolio_builder` | `standard` | Paid feature |
| `billing_support` | `free` | Available to anyone with an account so they can ask about billing even when entitlements are gone |
| `supervisor` | `free` | The orchestrator itself; available to anyone who reaches the endpoint |
| `interrupt_agent` | `standard` | Proactive; only acts on paid students |

`billing_support` and `supervisor` being free-tier-accessible matters: a student whose subscription expired can still ask "what happened to my account?" and get a real answer routed by the Supervisor through `billing_support`.

---

## Section C — The Free Tier Policy

Per the locked-in scope: free tier is narrowly defined, not a general "every signup gets X free agent calls" policy.

### C.1 Who gets free tier

Three triggers grant temporary free-tier state:

1. **First 24 hours after signup** — a `signup_grace` free-tier window. Lets new students try the placement quiz, demo chat, and onboarding without payment friction.
2. **Active placement-quiz session** — a per-session free-tier window. Lets the placement quiz function even if the student doesn't have a paid course yet.
3. **Demo chat session** — explicit demo flows have their own free-tier marker. Currently this is the public `/api/v1/demo/chat` endpoint; gets folded into the agentic flow during D9 cleanup.

Each is represented as a row in a new `free_tier_grants` table:

```sql
CREATE TABLE free_tier_grants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    grant_type TEXT NOT NULL CHECK (grant_type IN (
        'signup_grace',
        'placement_quiz_session',
        'demo_chat'
    )),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_ftg_user_active ON free_tier_grants (user_id, expires_at)
WHERE revoked_at IS NULL;
```

When `compute_active_entitlements` runs, it joins this table and includes any non-expired, non-revoked grant in the `EntitlementContext.free_tier` field.

### C.2 Free tier limits

Defined in `TIER_CONFIGS["free"]` above:

- Daily cost ceiling: **5 INR/day**
- Burst rate limit: **3 calls/minute**
- Hourly rate limit: **20 calls/hour**
- Allowed agents: **billing_support, supervisor, plus placement-flow specialists when those exist**

These are tighter than standard tier by 10x on cost, 3x on burst, 5x on hourly. Tight enough to prevent abuse; generous enough for a placement quiz to actually work.

### C.3 Free tier UX

When a free-tier user requests an agent outside their allow-list, the Supervisor declines gracefully:

```json
{
  "action": "decline",
  "decline_reason": "entitlement_required",
  "decline_message": "I can help with your placement quiz and account questions during your trial. To get personalized code reviews, career coaching, and interview prep, you'll want to enroll in a course. Browse what's available?",
  "suggested_next_action": "browse_catalog"
}
```

When the daily cost ceiling is hit:

```json
{
  "action": "decline",
  "decline_reason": "cost_exhausted",
  "decline_message": "You've used today's free trial allowance. It resets at midnight UTC. To unlock more, enroll in a course.",
  "suggested_next_action": "browse_catalog"
}
```

These messages are templates, not LLM-generated, to keep responses fast and predictable on rejections.

### C.4 Abuse prevention

Free-tier abuse vectors and mitigations:

| Vector | Mitigation |
|---|---|
| Sign up multiple times to get repeated 24h grace | Email verification required before grace activates; one grant per email |
| Spam placement_quiz_session grants | Each grant tied to a real placement_quiz_session row with a real start time; one active grant per user |
| Rate-limit evasion via parallel sessions | Rate limits are per `user_id`, not per session |
| Generate cost via fast-failing agent calls | Failed calls count against ceiling unless they fail at Layer 1 (auth/entitlement) |

Persistent abusers can be flagged by adding a `metadata.abuse_flag = true` to their user row, which is checked in Layer 1 before granting any free-tier state.

---

## Section D — Cost Ceiling Implementation

Per-student per-day cost tracking. Decisions tighten as cost rises.

### D.1 Schema for cost tracking

Existing `agent_actions` table already has `tokens_used` (D1). Existing `agent_tool_calls` has cost tracking. Pass 3f adds a per-student rollup view for fast lookup:

```sql
-- Materialized view, refreshed every 60 seconds, used for fast budget checks
CREATE MATERIALIZED VIEW mv_student_daily_cost AS
SELECT
    student_id AS user_id,
    DATE(created_at AT TIME ZONE 'UTC') AS day_utc,
    SUM(COALESCE(cost_inr, 0)) AS cost_inr_total,
    COUNT(*) AS action_count
FROM agent_actions
WHERE created_at >= now() - interval '7 days'
GROUP BY student_id, DATE(created_at AT TIME ZONE 'UTC');

CREATE UNIQUE INDEX idx_mv_sdc_user_day ON mv_student_daily_cost (user_id, day_utc);
```

Refresh policy: a Celery beat job runs every 60 seconds calling `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_student_daily_cost`. Stale-by-up-to-60s is acceptable because:

- The cost ceiling is a soft cap, not a hard cutoff at the rupee
- 60 seconds of drift at 50 INR/day means worst-case ~5% over-grant before the next refresh
- Acceptable tradeoff vs. real-time computation on every request

Real-time alternative (rejected): query `agent_actions` directly on every request. Each request becomes O(N) over the day's actions; at 5000 requests/day per user that's 25M index reads/day. The materialized view is cheap.

### D.2 Cost computation flow

```
1. Each agent run writes its cost to agent_actions.cost_inr (existing infra)
2. mv_student_daily_cost refreshes every 60s
3. compute_active_entitlements() queries mv_student_daily_cost for today's total
4. EntitlementContext.cost_budget_remaining_today_inr = ceiling - today_total
5. Layer 1 / 2 / 3 check this value, decline if < target_capability.typical_cost_inr
```

### D.3 Cost ceiling configuration

Per-tier from `TIER_CONFIGS`:

- Free: 5 INR/day
- Standard: 50 INR/day

These are the launch numbers. They're calibrated:

- 50 INR/day × 30 days = 1500 INR/month per heavy user. At 1000 paid students, max monthly cost is 15L INR (~$18k USD). Bounds the worst case.
- A typical student doing a daily 30-minute session uses 5-15 INR/day. The 50 INR ceiling absorbs power users without bleeding to abusers.
- 5 INR free-tier ceiling is enough for a single substantive demo conversation (~10 LLM calls) but not enough to run multi-hour sessions for free.

Pass 3i (scale + observability) covers the dashboards for monitoring whether these numbers are calibrated correctly post-launch.

### D.4 Cost ceiling edge cases

**Mid-chain crossover.** Pass 3b §6.4 already handles: dispatch layer aborts the chain mid-flight when the next step would push over budget. The aborted-mid-chain message is part of the graceful response.

**Last-call overshoot.** A single agent call might exceed remaining budget mid-execution (started with 3 INR remaining, ended up costing 5 INR because the LLM produced more output than expected). We *don't* kill the call; we let it complete and the next call hits the cost-exhausted path. Killing mid-call would lose user-facing context for a saving of 1-2 INR.

**Refund during a chain.** Layer 3's fresh re-check catches this between dispatch steps. Already handled.

---

## Section E — Refund Revocation Propagation

Refunds revoke entitlement immediately. No grace period.

### E.1 The flow today (per Pass 1)

`entitlement_service.revoke_for_order(order_id)` exists and writes `revoked_at` on the matching `course_entitlements` row. It's called from refund processing in `payments_v2.py` via webhooks.

What's missing: the agent layer doesn't check entitlements at all (Pass 2 H1). Once Layer 1/2/3 are wired, revocation propagates automatically — the next call after revocation hits Layer 1, finds no active entitlements, returns 402.

### E.2 What about in-flight requests?

A student is mid-request when their refund processes. Three sub-cases:

**Sub-case 1: Revoked before Layer 1 runs.** Caught at Layer 1; 402 returned.

**Sub-case 2: Revoked between Layer 1 and Layer 2 (Supervisor LLM call running).** The Supervisor is reasoning over stale entitlement state. Layer 3's fresh re-check catches it before dispatch. Decline emitted.

**Sub-case 3: Revoked mid-dispatch, in a chain.** Layer 3's per-step re-check catches it before the next step. Chain aborts with a partial result.

**Sub-case 4: Revoked during a single specialist's execution.** Specialist completes the call. Cost charged. Next call hits 402. This is the maximum exposure: one trailing call after revocation. Acceptable.

### E.3 Refund-issued in-app messaging

When the dispatch layer rejects a request because of mid-flight revocation, the message is specific:

```json
{
  "action": "decline",
  "decline_reason": "entitlement_required",
  "decline_message": (
    "Your subscription was just refunded — that means your access to "
    "AI agents has ended. If this was unexpected, you can browse courses "
    "to re-enroll, or contact billing if you have questions."
  ),
  "suggested_next_action": "contact_support"
}
```

This message is distinct from the generic "you don't have an entitlement" message. The dispatch layer detects "entitlement existed at Layer 1 but doesn't at Layer 3" → sets a `recently_revoked` flag → message template selected accordingly.

---

## Section F — Edge Cases

### F.1 Admin-on-behalf-of

Admin endpoints can invoke agents for support/debugging purposes (e.g., `POST /api/v1/admin/agents/{name}/trigger`). These bypass entitlement checks because the admin's permissions, not the student's, govern access.

Implementation: a separate dependency `require_admin_or_entitled` is used on admin-callable agent routes. The DISC-57 actor identity columns (`actor_id`, `actor_role`, `on_behalf_of`) on `agent_actions` already capture the admin context. No additional schema needed.

The Supervisor sees admin-on-behalf-of requests with `actor_role="admin"` in `SupervisorContext` and adapts its reasoning accordingly (e.g., admin asking "what would you tell this student" gets routed differently than the student asking themselves).

### F.2 Bundle entitlements

`course_bundles` (D1) lets a single order grant entitlement to multiple courses. The `expand_bundle` function in `entitlement_service.py` already handles this. Pass 3f doesn't change this; bundle entitlements show up in `EntitlementContext.active_entitlements` like any other entitlement.

### F.3 Comp'd / promotional accounts

Sometimes you want to grant standard-tier access without payment (beta testers, partner accounts, refund offers). These are `course_entitlements` rows with `metadata.granted_via = 'comp'` (or `'promotional'` etc.). Same code path; tracking metadata is for ops/admin visibility.

A small admin script `grant_comp_access(user_id, course_id, reason, granted_by_admin_id)` writes the row with appropriate metadata.

### F.4 Enrolled-but-inactive students

Students with active entitlements who haven't logged in for weeks are still entitled. Their entitlement remains active until it's explicitly revoked or expires. Different from "free tier expired" — paid entitlements don't auto-expire on inactivity.

(`course_entitlements` does not currently have an `expires_at` column. If subscription-based pricing ever ships, that's added; until then, paid access is until-revoked or until-course-completion-defined-end.)

### F.5 Webhook-triggered agent runs

`content_ingestion` runs from GitHub webhooks (Pass 1, D6). These bypass entitlement checks because:

- The actor is the system (`actor_role="system"`)
- The agent is `requires_entitlement=False` per its capability declaration
- No human is being billed; ingestion cost is platform overhead

### F.6 Background Celery tasks

Celery-driven agent runs (`weekly-letters` invoking `progress_report`, `risk-scoring-nightly` writing risk signals) bypass entitlement checks for the same reason as webhooks. The Supervisor and dispatch layers aren't involved in these flows; they're direct invocations via the existing Celery infra.

Cost is tracked but not charged against student daily ceilings (it's platform-driven engagement, not student-initiated). Per-task cost dashboards live in Pass 3i.

### F.7 Free-tier user finishes placement quiz, doesn't enroll

The placement_quiz_session free-tier grant expires when the session ends. After expiration, the user is back to "no active entitlement." Their next message hits 402 with `next_action="browse_catalog"`.

Their conversation history persists (memory bank, conversation thread). When/if they enroll later, that history is intact.

### F.8 Frontend-side state desync

The frontend (frozen for now) caches some entitlement state for UX (course unlocking display, etc.). When backend revokes entitlement but frontend cache is stale, the user sees "your course is unlocked" but their next agent call returns 402.

Mitigation:

1. The 402 response includes `X-Entitlement-Updated: true` header for the frontend to invalidate its cache and refresh.
2. The 402 body includes `next_action` so the UI can render an appropriate prompt.

The frontend changes to honor `X-Entitlement-Updated` are deferred until you're ready to touch the frontend (post-launch). In the interim, a manual page refresh fixes the desync.

---

## Section G — Implementation In D9

Most of Pass 3f ships in D9 because entitlement gating is a launch blocker.

### G.1 D9 scope additions for Pass 3f

Beyond the Supervisor scope from Pass 3b §13.1, D9 also ships:

**New files:**
- `backend/app/api/v1/dependencies/entitlement.py` — extended with `require_active_entitlement` (Layer 1)
- `backend/app/services/entitlement_service.py` — extended with `compute_active_entitlements` returning `EntitlementContext`
- `backend/app/core/tiers.py` — `TIER_CONFIGS` configuration
- `backend/app/schemas/entitlement.py` — `EntitlementContext`, `ActiveEntitlement`, `FreeTierState`, etc.

**New tables (in migration 0057):**
- Add `tier` column to `course_entitlements`
- Create `free_tier_grants` table
- Create `mv_student_daily_cost` materialized view
- Index for entitlement lookup

**Wired into existing flows:**
- The canonical `/api/v1/agentic/{flow}/chat` endpoint mounts `Depends(require_active_entitlement)`
- The orchestrator passes `EntitlementContext` to the Supervisor in `SupervisorContext`
- The dispatch layer re-fetches `EntitlementContext` between Supervisor decision and specialist call
- A new Celery beat job refreshes `mv_student_daily_cost` every 60 seconds
- Signup flow grants a 24-hour `signup_grace` free-tier row
- Placement-quiz session start grants a `placement_quiz_session` free-tier row

**Tests:**
- Unit tests for tier filtering, cost ceiling, free-tier window expiration
- E2E tests:
  - Unentitled user gets 402 from canonical endpoint
  - Newly-signed-up user gets 24-hour free-tier access
  - Free-tier user can call billing_support but not senior_engineer
  - Standard user with cost-exhausted budget gets graceful decline
  - Refunded user (mid-chain) gets chain abort with appropriate message

### G.2 What's NOT in D9 (deferred to follow-up deliverables)

- The admin "comp grant" CLI tool — small, post-launch
- Premium tier definition — not needed until premium ships as a SKU
- Frontend changes for cache invalidation — frontend frozen
- Sophisticated abuse-flagging — basic per-email-per-grant prevention only in v1; ML-driven abuse detection is a Pass 3i / future concern
- Per-feature granular entitlements (e.g., "you've bought course X but the resume_reviewer feature is a separate add-on") — not needed for "all-paid-or-none" model

---

## Section H — Monitoring And Calibration

How to know if entitlement enforcement is working and calibrated correctly.

### H.1 Operational metrics (PostHog / structlog)

New events emitted:

- `entitlement.gate_denied` (Layer 1 hit, properties: `gate_layer=1`, `reason`)
- `entitlement.supervisor_declined` (Layer 2 decline, properties: `decline_reason`, `target_agent`)
- `entitlement.dispatch_blocked` (Layer 3 hit, properties: `target_agent`, `time_since_layer_1_ms`, `reason`)
- `entitlement.free_tier_granted` (signup grace or session granted)
- `entitlement.free_tier_expired` (free tier window ended)
- `entitlement.cost_ceiling_hit` (student exhausted daily budget)

Dashboards (built in Pass 3i):

- "How many requests are denied at each layer per day?" — distribution across Layer 1/2/3
- "Free-tier conversion rate" — how many signup_grace users go on to enroll
- "Cost ceiling distribution" — what % of paid students hit ceiling, how often, in what hour of the day
- "Mid-chain revocations" — count of Layer 3 catches; should be near-zero in steady state

### H.2 Calibration signals

Things that suggest the gates are wrong:

- **Many cost_exhausted events for paying students** → ceiling is too tight, raise it
- **Near-zero cost ceiling events** → ceiling is too loose, lower it (or it's just generous; check distribution)
- **Many free-tier-expired-with-no-enrollment** → free tier is too good (doesn't drive conversion) OR onboarding is broken
- **Many Layer 1 denials from logged-in users** → entitlement state is being computed wrong OR users are revisiting after expiration

These signals get reviewed weekly post-launch for the first 6 weeks, then monthly.

### H.3 Calibration overrides

Per-student overrides for special cases:

```sql
-- Example: VIP student gets standard tier with 3x cost ceiling
UPDATE course_entitlements
SET metadata = jsonb_set(metadata, '{cost_ceiling_inr_override}', '"150.00"')
WHERE user_id = '...' AND tier = 'standard';
```

`compute_active_entitlements` honors metadata overrides if present. Used sparingly.

---

## Section I — Cost And Complexity Of This Layer

### I.1 Build cost (D9)

- New schema migration: small (1 ALTER + 1 CREATE TABLE + 1 CREATE MATERIALIZED VIEW)
- Layer 1 dependency: ~50 LOC + tests
- Tier configuration module: ~100 LOC
- `EntitlementContext` schema: ~80 LOC
- Layer 3 re-check integration in dispatch layer: ~80 LOC
- Supervisor prompt addition for tier-aware reasoning: prompt edits, no code
- Free-tier grant flow (signup, placement quiz): ~150 LOC across the relevant services
- Materialized view refresh job: ~30 LOC
- Tests: ~40 unit tests + ~10 E2E tests

Total: ~600-800 LOC. Modest. The complexity is in the *correctness* of the three-layer interaction, not the volume of code.

### I.2 Runtime cost

- Layer 1: 1 query per request, ~5ms
- Layer 3: 1 cache lookup per dispatch step, ~1ms
- Materialized view refresh: 60-second job, ~1 second of DB work per refresh

Negligible at scale.

### I.3 Operational cost

- One new Celery beat job to monitor (refresh cadence)
- One new materialized view to monitor (size, refresh duration)

Both included in standard Postgres / Celery monitoring already.

---

## Section J — What This Pass Earns

When D9 ships:

**For students:**
- Their paid course actually unlocks the agents (the Pass 2 H1 finding closed)
- Free-tier flows still work (placement quiz, demo, onboarding) without payment friction
- Refunds revoke access cleanly with clear messaging
- Cost ceiling protects them from runaway charges; clear messaging when hit
- Tier upgrades become a future possibility without re-architecture

**For the operator:**
- The "anyone can call any agent" security/business hole is closed
- Entitlement state is computable, observable, and auditable
- Cost is bounded per-student, per-tier
- Free tier abuse is structurally limited
- Adding premium tier is a config change

**For future contributors:**
- The three-layer pattern is a recognizable, documented invariant
- `EntitlementContext` is a single source of truth for "what can this user do right now"
- Tier configuration in code, reviewed via PR
- Edge cases (refunds, comps, admin-on-behalf-of, free-tier windows) are documented

This is the layer that makes AICareerOS a real business with real entitlements, not a free-for-all chatbot platform.

---

## Section K — What's Deferred

- **Premium tier definition** — when needed
- **Per-feature entitlements** — out of scope for "course unlocks all agents" model
- **Frontend cache invalidation** — frontend frozen
- **Subscription-based pricing** (`expires_at` on entitlements) — when the SKU ships
- **ML-driven abuse detection** — basic prevention only in v1
- **Granular cost ceilings per agent** — system-wide daily cap is enough for v1

---

## What's NOT covered by Pass 3f

- **Output-side safety, prompt injection, content moderation** → Pass 3g
- **Interrupt agent design** → Pass 3h
- **Scale + observability + cost dashboards** → Pass 3i
- **Naming sweep + cleanup** → Pass 3j
- **Implementation roadmap synthesis** → Pass 3k/3l

Each builds on this layer without modifying it.
