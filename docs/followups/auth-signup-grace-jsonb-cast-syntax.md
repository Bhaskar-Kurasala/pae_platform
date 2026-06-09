# auth.signup_grace_failed — `:meta::jsonb` cast syntax error

**Status:** Open. **Severity: PENDING** — depends on investigation
outcome.
**Origin:** Surfaced as a side-observation while diagnosing
BUG-CP4-LESSON-FK-500 (D18 Phase B CP4, 2026-05-09).
**Owner:** backend team; investigation should land before launch.

## What this is

Backend logs show every signup since this regression landed has
been silently failing the `free_tier_grants` write:

```
ERROR: <class 'asyncpg.exceptions.PostgresSyntaxError'>:
    syntax error at or near ":"
[SQL: INSERT INTO free_tier_grants (id, user_id, grant_type,
    granted_at, expires_at, metadata) VALUES
    ($1, $2, 'signup_grace', $3, $4, :meta::jsonb)]
event: auth.signup_grace_failed
level: warning
```

The SQL string contains `:meta::jsonb` — SQLAlchemy `text()`
named-parameter syntax mixed with a typed cast — but Postgres
receives the raw `:meta` (positional-parameter context) and
chokes. The auth service's "Best-effort" wrapper catches the
`asyncpg.exceptions.PostgresSyntaxError`, logs the warning,
swallows the failure, and lets registration succeed.

## Why this matters

Three categories of unknown:

1. **Free-tier-grant accumulation drift.** Every user registered
   since the regression has zero `free_tier_grants` rows. The
   entitlement system may have a fallback (free students get
   "default" entitlements without an explicit grant) OR the
   table may be load-bearing for the free-tier flow. **Unknown.**
2. **User-visible impact.** Are users created during the regression
   window discovering they have less access than free-tier users
   created earlier? **Unknown.**
3. **Backfill question.** If the grant table IS load-bearing,
   every affected user needs a backfilled grant row. The fix
   isn't just "fix the SQL"; it's "fix the SQL + backfill all
   affected rows."

## Pattern candidate: log-vs-reality drift

Application logs say signup is healthy (`auth.register` event
emits at level=info; grant-failed emits at level=warning). The
warning is buried in normal log volume; nobody reading the logs
during routine ops would notice. Meanwhile, the grants table
silently accumulates the gap.

This is a different pattern from Pattern 27 (consumer convention
drift) or Pattern 29 (scaffolded-but-inert): it's
**catch-and-warn-and-continue masking a real failure**. The
"best-effort" wrapper that protects user-facing reliability
(signup doesn't 500 just because the grant write failed) makes
the failure invisible.

Worth registering as a candidate pattern at CP5 if a second
instance surfaces in Phase C. Provisional name:
**Pattern candidate 35 — silent-warning masking real failure**.

## Investigation steps (preliminary)

1. **Locate the regression.** `git log -p backend/app/services/`
   for the file that produces this query; find the commit that
   introduced the `:meta::jsonb` syntax. Determine when the
   regression landed.
2. **Count affected rows.**
   `SELECT COUNT(*) FROM users WHERE created_at >= <regression_landed>`
   gives the upper bound on affected users.
   `SELECT COUNT(*) FROM free_tier_grants` should be far smaller
   if the bug is real.
3. **Trace downstream consumers of `free_tier_grants`.** Is
   there a fallback in the entitlement service? Does the missing
   grant manifest as user-visible degradation?
4. **Decide fix shape.** Likely `metadata=:meta` with proper
   parameter binding (via `bindparams` or kwargs to `text()`),
   PLUS a backfill migration for affected users.

## Why captured as a follow-up, not fixed during CP4

CP4's scope was authoring tests, not fixing arbitrary bugs the
tests surface. BUG-CP4-LESSON-FK-500 is the explicitly-traceable
test finding. This signup-grace bug surfaced as a log-side
observation during debugging — different surface, different
investigation cost, different ownership (backend team / auth
domain).

The fix is preserved here so Phase C can pick it up before
launch as a launch-readiness item.

## Cross-references

  * `docs/followups/bug-cp4-lesson-fk-500.md` — the bug whose
    diagnosis surfaced this side-finding (Related observation
    section).
  * `backend/app/services/auth_service.py` — the wrapper that
    catches and logs the failure silently.
  * `backend/app/models/free_tier_grant.py` (or equivalent) —
    the schema this query targets.
