# Follow-up: swap the EscalationLimiter to a redis-backed implementation

**Owner:** _unassigned — pick up before D8 ships._
**Status:** **BLOCKING** before `enable_proactive=True` lands in prod.
**Created:** 2026-05-02
**Last update:** 2026-05-02 — escalation level raised after D6
review. Proactive infra is now ready (D6); the moment a real
proactive flow turns on (D8), the multi-worker over-grant becomes
production behaviour, not theoretical risk.

**Do not enable proactive flows in prod until this is resolved.**
Set `settings.enable_proactive=False` (default) until the redis-
backed limiter ships. Code can land in dev with proactive on; prod
must wait.

**Triggered by:** D5 (`evaluation.py`) shipped a process-local
in-memory rate limiter. D6 makes proactive flows live, which means
Celery workers (already multi-process by design) will start
evaluating agents on cron schedules — pushing this from
"theoretical over-grant" to "production over-grant."

## Problem

`EscalationLimiter` in `app/agents/primitives/evaluation.py` is
process-local: each worker carries its own deque of timestamps.

For a single-process backend (current dev) the budget is exact:
`limit_per_agent=5/hour` means at most 5 admin notifications per
hour for a given agent.

For multi-worker deploys the effective budget multiplies:
- 1 FastAPI worker + 1 Celery worker = 2× over-grant (10/hr)
- 4 Gunicorn workers + 2 Celery workers = 6× over-grant (30/hr)

Production runs with multiple workers. As soon as D6 lands and
Celery starts firing proactive evaluations, a noisy agent's
notification fan-out scales with worker count instead of being
clamped by the per-agent budget.

## Proposed fix

Implement `RedisEscalationLimiter` with the same `should_notify(agent_name)`
API. Backing store: a sorted set per agent keyed `escalation:{agent}`
where members are unique-ish ids (e.g. `f"{ts}:{uuid4()}"`) and
scores are unix timestamps. `should_notify` does:

1. `ZREMRANGEBYSCORE escalation:{agent} -inf {now - window}` — drop
   expired entries
2. `ZCARD escalation:{agent}` — current count in window
3. If count >= limit, return False (no zadd, doesn't extend bucket)
4. Else `ZADD escalation:{agent} {now} {now}:{uuid4()}` and return True

Atomic via Lua script (or `MULTI/EXEC` if Lua's overkill); single
round-trip. Set a TTL on the key (`EXPIRE escalation:{agent} {2 *
window}`) so abandoned agents don't leak keys forever.

Module-level singleton swap: `escalation_limiter` resolves to
`RedisEscalationLimiter` when `settings.redis_url` is set and the
client connects, falls back to `EscalationLimiter` (in-memory)
otherwise. The fallback path is what dev / single-worker / CI use.

## Done when

- [ ] `RedisEscalationLimiter` lands with the same API
- [ ] Module-level `escalation_limiter` chooses redis when available,
      falls back to in-memory cleanly
- [ ] Test (using fakeredis or live redis) proves multi-process
      semantics: spawn N "workers" against the same redis, count
      `notified_admin=True` rows, assert == limit (not N × limit)
- [ ] Dev fallback test: redis unreachable → uses in-memory,
      doesn't crash on construction

## Why this isn't urgent today

Backend currently runs single-process in dev (one Gunicorn worker
+ one Celery worker → 2× over-grant). Proactive flows are off until
D6 lands. The window opens the moment we increase worker count
beyond 2 OR turn on proactive automation; do this before either.

## References

- Current implementation: `backend/app/agents/primitives/evaluation.py`
  → `EscalationLimiter`
- Acknowledgement of the over-grant in the class docstring
- Redis client already in use: `app/core/redis_client.py` /
  `redis_url` setting
- Migration: `backend/alembic/versions/0054_agentic_os_primitives.py`
  → `agent_escalations.notified_admin` column
