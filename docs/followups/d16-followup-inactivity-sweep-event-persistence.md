# D16 follow-up — inactivity_sweep event persistence + auto-consumption

**Status:** Open. Post-launch.
**Created:** 2026-05-08 (D16/CP2 closure).

## What this is

CP1 finding (h): `inactivity_sweep` Celery task logs `re_engagement.flagged`
to **structlog only**. No DB row is written. The pre-CP2 docstring
claimed `disrupt_prevention` "consumes these via the chat/agents
surface" — that's not wired. Re-engagement messaging today fires only
via the admin cockpit's manual "trigger agent" button (which dispatches
disrupt_prevention with an explicit user_id).

CP2.h fixed the docstring to reflect actual behavior. This follow-up
captures the **post-launch** wiring work that would close the gap
properly: when an inactive student returns to the chat surface, fire
disrupt_prevention automatically based on a recent flag.

## Two implementation paths

**Path A: persist flag events to a queryable table**

- New table `re_engagement_flags(user_id, flagged_at, days_inactive,
  consumed_at)` — append-only, `consumed_at IS NULL` means pending.
- `inactivity_sweep` writes a row per inactive user (idempotent via
  unique partial index on `(user_id) WHERE consumed_at IS NULL`).
- Chat-surface entry hook checks `re_engagement_flags WHERE user_id=?
  AND consumed_at IS NULL ORDER BY flagged_at DESC LIMIT 1`; if a row
  exists, dispatch `disrupt_prevention`, mark `consumed_at = now()`.

   Pros: explicit table, easy to query for "students flagged but not yet
   re-engaged", auditable.
   Cons: yet another table; some overlap with `outreach_log` and
   `student_inbox`.

**Path B: read from the log backend**

- Sweep continues to log structlog only.
- Chat-surface entry hook queries Loki / Sentry / whatever the log
  aggregator is, looking for recent `re_engagement.flagged` events for
  the current user_id.

   Pros: zero schema change.
   Cons: log aggregator availability becomes a runtime dependency for a
   user-facing path; query latency is unpredictable; not portable across
   log backends.

Path A is preferred. Path B is a "if we really don't want a new table"
fallback.

## When to revisit

When re-engagement throughput becomes a measurable retention signal,
i.e. when admins begin asking "did the inactive cohort actually return,
and what did they hit when they did?" Until then, the cron is observational
and admin-driven re-engagement covers the workflow.

## Cross-references

- `backend/app/tasks/inactivity_sweep.py` — task with CP2.h-corrected
  docstring.
- `docs/architecture/d16-functional-audit.md` finding (h).
- `backend/app/agents/disrupt_prevention.py` — current consumer
  (chat-surface, admin-triggered today).
