# Follow-up: hot-recovery for the EscalationLimiter Redis backend

**Owner:** _unassigned — revisit when worker lifetime > 24h or when
student volume makes the over-grant visible._
**Status:** open (not urgent)
**Created:** 2026-05-02
**Triggered by:** Track 2 review note. The Redis-backed limiter
shipped with boot-time + runtime fail-open, but no hot-recovery.

## Behaviour today

`make_escalation_limiter()` runs once at module import. If Redis
is reachable: returns `RedisEscalationLimiter`. If Redis is
unreachable: returns the in-memory `EscalationLimiter` and logs
`escalation_limiter.redis_unreachable_at_boot` with the
"permissive across workers" warning.

Once that choice is made, the worker stays in whichever mode it
booted into until the worker process restarts. A worker that
booted with Redis down stays in-memory permanently — even after
Redis comes back. A worker that booted with Redis up stays
Redis-backed; runtime Redis failures fail-open per call (correct
behaviour, see `RedisEscalationLimiter.should_notify` and the
`test_redis_limiter_fail_open_when_redis_unreachable` test) but
do NOT downgrade the instance.

## Why this is acceptable today

Production deploys cycle workers regularly (every release rebuilds
the Celery image). Worker lifetime is bounded by the deploy
cadence. If Redis is down at boot:
  • The boot probe logs the degradation immediately
  • Operators page on it
  • Next deploy after Redis returns picks up the right backend

The window where "Redis is fine but my worker is still in-memory"
is bounded by the time between Redis recovery and the next deploy.
For the current cadence + worker count, that's a few hours of
over-grant on admin notifications — visible in audit rows but
not load-bearing.

## When to revisit

Two triggers:
1. **Worker lifetime exceeds 24h.** If we ever stop redeploying
   daily, the in-memory-after-Redis-recovers window stretches.
   Hot-recovery becomes worth it.
2. **Student volume makes over-grants visible.** At a few hundred
   students the over-grant is statistical noise. At 10k+, with
   N workers, an in-memory limiter that should cap at 5/hr per
   agent might page admins 5N times instead. That's the volume
   where the on-call complaint surfaces and someone files a
   ticket pointing here.

## Implementation sketch (when the time comes)

Periodic re-probe inside `RedisEscalationLimiter` (or a wrapper):
- Every N minutes (5 is a reasonable starting point), the next
  `should_notify` call triggers a background `PING`.
- If PING succeeds and we were in fallback mode, swap the
  instance under a lock.
- If PING fails and we were Redis-backed, log but don't
  downgrade — runtime fail-open already covers correctness.

The lock keeps concurrent should_notify calls from seeing a
half-swapped state. The 5-minute interval keeps the PING
overhead negligible (one round-trip per 5 minutes per worker).

A simpler alternative: re-probe on every Nth call (e.g., every
1000th). Trades probabilistic latency on rare calls for no
background timer thread.

## Done when

- [ ] Hot-recovery shipped, with a test that simulates "Redis
      down at probe → up later" and proves the next call uses
      the Redis backend
- [ ] Operations runbook updated to note that workers self-heal
      from Redis outages without restart
- [ ] Resolution noted at the top of this file (don't delete —
      the trail of resolved follow-ups is itself useful)

## References

- Track 2 implementation: `backend/app/agents/primitives/evaluation.py`
  → `RedisEscalationLimiter`, `make_escalation_limiter`
- Resolved follow-up: `docs/followups/escalation-limiter-redis.md`
  (the broader Redis swap; this file is a downstream refinement)
- Track 2 commit: `ec18a9b` (`feat(agentic-os): track-2 — RedisEscalationLimiter`)
