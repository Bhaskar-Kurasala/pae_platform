# study_planner proactive trigger — deferred to D16

**Status:** Deferred. Declared in D12 CP1 (`uses_proactive=True` flag
set on `StudyPlannerAgent`). Implementation owned by D16.
**Created:** 2026-05-06 (D12 CP1).
**Deliverable:** D16 (proactive layer, per Pass 3kl §B.8).
**Cross-references:** Pass 3c E4 lines 862, 924-932;
`backend/app/agents/study_planner_v2.py` (the `uses_proactive=True` flag).

## What was declared in D12

`study_planner_v2.py` sets `uses_proactive: ClassVar[bool] = True`.
This is intentional — D16 reads this flag to wire the nightly trigger
without having to search for the agent. The flag declares intent;
it does NOT trigger any cron registration in D12.

**Exactly what D12 ships:**
- `uses_proactive = True` on the class (flag only)
- No `@proactive(cron="0 22 * * *")` decorator
- No `nightly_adherence_check` method body
- No Celery beat entry

## What D16 implements

Per Pass 3c E4 lines 924-932, the full implementation:

```python
from app.agents.primitives.proactive import proactive

class StudyPlannerAgent(AgenticBaseAgent[StudyPlannerInput]):
    uses_proactive = True

    @proactive(cron="0 22 * * *")  # 10 PM IST every night
    async def nightly_adherence_check(self) -> None:
        """For each active student with a goal_contract, run adherence_check mode.

        Steps:
        1. Query all users with a non-expired goal_contract (uses migration 0060
           expires_at column to find active contracts).
        2. For each, check today's plan:session:{date} memory key (committed
           by commit_plan) against their interaction:plan_adherence:{date}
           (written by track_adherence).
        3. If adherence is dropping (adherence_score < 0.5 for 2+ consecutive
           days), write a low-adherence signal to memory and optionally trigger
           an interrupt.
        4. Use escalation_limiter to prevent more than one proactive interrupt
           per student per 24h window.
        5. Log via log_event for D17 dashboards.
        """
        ...
```

## Infrastructure D16 must provide

1. **`@proactive` decorator** in `app/agents/primitives/proactive.py`
   — reads the cron schedule from the decorator arg, registers the
   method with Celery beat. Already partially scaffolded in D9; D16
   finalises it.
2. **Celery beat registration** in `app/core/celery_app.py` — the
   `register_proactive_schedules(celery_app)` call at startup reads
   all `AgenticBaseAgent` subclasses with `uses_proactive=True` and
   wires their cron methods.
3. **Escalation limiter** for proactive interrupts — ensures one
   interrupt per student per 24h. The infrastructure lives in
   `app/agents/primitives/evaluation.py::EscalationLimiter`; D16
   wires it to the proactive path.
4. **Interrupt target** — if adherence check decides the student
   needs a push notification or in-app message, it calls
   `interrupt_agent` (D16 deliverable) to trigger the next-session
   prompt.

## Query for active goal contracts (D16 implementation guidance)

```sql
SELECT user_id, weekly_hours, target_role, deadline_months
FROM goal_contracts
WHERE expires_at IS NULL OR expires_at > now()
ORDER BY created_at DESC
```

Use asyncpg-rollback discipline per
`docs/followups/asyncpg-rollback-discipline.md`.

## Cross-references

- Pass 3c E4 lines 862, 924-932 — the full spec
- `backend/app/agents/study_planner_v2.py` — `uses_proactive=True` flag
- `backend/app/agents/primitives/proactive.py` — the decorator scaffold
- `backend/app/core/celery_app.py::register_proactive_schedules` — the
  boot-time wiring entry point
- `docs/followups/escalation-limiter-redis.md` — the Redis-backed
  per-student rate limiter D16 needs to ship
- Pass 3kl §B.8 — D16 deliverable scope (proactive layer)
