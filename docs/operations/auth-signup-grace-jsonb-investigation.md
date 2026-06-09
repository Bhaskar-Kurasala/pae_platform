# auth-signup-grace-jsonb — investigation findings

**Status:** Investigation complete (2026-05-13). Fix landed in
same commit. Backfill execution pending founder run against
production DB.
**Severity:** **HIGH** for any production user signed up during
the regression window without a paid entitlement attached at
signup. **LOW** for users who arrive with a paid entitlement
because the paid path masks the missing free-tier grant.

This investigation closes the D18-deferred / D19.5-gated item.
The investigation produced the empirical evidence the D19.5 gate
explicitly asked for ("conditional on cohort-1 enrollment model
— silent free-tier-grant failure"); the answer to that
conditional now sits below.

## a. Root cause

`backend/app/services/entitlement_service.py:677` and `:732`
emit:

```sql
INSERT INTO free_tier_grants (..., metadata) VALUES (..., :meta::jsonb)
```

The `::jsonb` is intended as a PostgreSQL typecast. **It is
parsed by asyncpg / SQLAlchemy as a second named-parameter
introduction** because both `:meta` (the bind parameter) and
`::` (the cast operator) share the colon delimiter. Concretely:

  * SQLAlchemy's text-mode parameter regex matches `:meta`,
    treats it as bind param.
  * The trailing `::jsonb` is then seen as another colon
    introducer; asyncpg's SQL preparer chokes on the malformed
    parameter reference.
  * Result: `PostgresSyntaxError: syntax error at or near ":"`.

**Canonical mechanism already documented in the codebase** at
[`backend/app/agents/tools/agent_specific/billing_support/escalate_to_human.py:182`](../../backend/app/agents/tools/agent_specific/billing_support/escalate_to_human.py)
— the escalate_to_human path encountered the same bug, diagnosed
it, and worked around it by **dropping the `::jsonb` cast
entirely**. Postgres auto-casts the JSON-shaped text payload
to the JSONB column type at INSERT because the column declares
JSONB. The cast was never needed; it was a defensive habit that
turns out to fight the bind-parameter parser.

The fix that landed at the same commit as this investigation:
remove the `::jsonb` suffix at both call sites. The `metadata`
column in `free_tier_grants` is `JSONB NOT NULL DEFAULT '{}'::jsonb`
([`alembic/versions/0057_entitlement_tier.py:104`](../../backend/alembic/versions/0057_entitlement_tier.py));
the column-level type drives the auto-cast.

## b. Regression window

  * **First emitted:** commit `1df4b3d` "feat(agentic-os): D9 —
    Supervisor + entitlement + safety + trace foundation",
    authored 2026-05-03 11:01:07 IST. Both line 677 and line 732
    introduced in the same D9 commit.
  * **Fixed:** the commit this doc lands in (2026-05-13).
  * **Window length:** ~10 days.

## c. Downstream impact

When `grant_signup_grace()` raises the syntax error, the caller
swallows it (`auth_service.py:90`) and logs
`auth.signup_grace_failed` at WARNING. Signup itself succeeds —
the user row is created and the auth path returns 200.

The user then hits the agentic endpoint for the first time. The
sequence:

  1. `compute_active_entitlements()` ([entitlement_service.py:601](../../backend/app/services/entitlement_service.py))
     runs.
  2. `_active_free_tier_grant(user_id)` returns `None` because
     no row exists in `free_tier_grants` for this user.
  3. `_active_paid_entitlements_full(user_id)` returns `[]` if
     the user has no paid entitlement.
  4. `_resolve_effective_tier(paid=[], free=None)` falls through
     to the defensive default at
     [entitlement_service.py:509](../../backend/app/services/entitlement_service.py)
     — but immediately after, `EntitlementContext.is_empty()`
     evaluates `True` because `active_entitlements` is empty
     and `free_tier is None`.
  5. `AgenticOrchestratorService.process_request` short-circuits
     at [agentic_orchestrator.py:117-131](../../backend/app/services/agentic_orchestrator.py)
     with `block_reason="no_active_entitlement"` and the user-
     facing message *"Your AICareerOS subscription has expired
     or you haven't purchased a course yet."*
  6. **The user is unable to use the platform.** There is no
     fallback path that papers over a missing signup_grace
     row; signup_grace IS the default-on-signup grant the
     system relies on for free-trial UX.

**The blast radius is the intersection of**:
  * `users` created since 2026-05-03 11:01:07 IST
  * AND `role = 'student'`
  * AND `is_deleted = false`
  * AND NO active paid `course_entitlements` row

**Paid users are NOT affected** — they hit `compute_active_entitlements`
with at least one active paid row, `is_empty()` returns False,
and the orchestrator proceeds.

## d. Affected user count (dev DB sanity check)

```sql
-- run against the dev DB at investigation time (2026-05-13):
SELECT
  (SELECT COUNT(*) FROM users
   WHERE created_at >= '2026-05-03 11:01:07+05:30')                AS total,
  (SELECT COUNT(*) FROM users
   WHERE created_at >= '2026-05-03 11:01:07+05:30' AND role='student') AS students,
  (SELECT COUNT(*) FROM users u
   WHERE u.created_at >= '2026-05-03 11:01:07+05:30'
     AND u.role='student' AND u.is_deleted=false
     AND EXISTS (SELECT 1 FROM free_tier_grants ftg
                 WHERE ftg.user_id=u.id AND ftg.grant_type='signup_grace'))
                                                                   AS with_grant,
  (SELECT COUNT(*) FROM users u
   WHERE u.created_at >= '2026-05-03 11:01:07+05:30'
     AND u.role='student' AND u.is_deleted=false
     AND NOT EXISTS (SELECT 1 FROM free_tier_grants ftg
                     WHERE ftg.user_id=u.id AND ftg.grant_type='signup_grace'))
                                                                   AS missing_grant,
  (SELECT COUNT(*) FROM users u
   WHERE u.created_at >= '2026-05-03 11:01:07+05:30'
     AND u.role='student' AND u.is_deleted=false
     AND EXISTS (SELECT 1 FROM course_entitlements ce
                 WHERE ce.user_id=u.id AND ce.revoked_at IS NULL))
                                                                   AS with_paid_entitlement;
```

Empirical result on dev DB (2026-05-13):

| Metric | Count |
|--------|-------|
| Total users created since regression | 93 |
| Of which student-role | 92 |
| Students with `signup_grace` grant | **0** |
| Students missing the grant | 92 |
| Students with at least one paid entitlement | 90 |
| **Students affected (missing grant AND no paid)** | **2** |

The "0 students with grant" confirms the bug fires 100% silently
(no successful grants land). Of 92 missing-grant students, 90
have paid entitlements that mask the missing grant, so only 2
would actually hit 402 on first agentic call **in the dev
environment**.

## d′. Production-DB count (founder runs)

The agent cannot reach production Neon DB. **Founder runs the
same query against production** to determine the production-side
affected count. Two scenarios:

  * **Cohort-1 is paid-at-signup** (every enrolled student has a
    course entitlement at signup): affected count likely 0;
    backfill is no-op. Confirms the LOW severity classification
    for this enrollment model.
  * **Cohort-1 includes free-trial / signup-grace-dependent
    users**: affected count > 0; each one is unable to use the
    agentic endpoint until backfilled.

Founder runs the query above against production via the
existing Neon read access (psql / Fly proxy / Neon UI's SQL
editor). Report the `missing_grant - with_paid_entitlement`
delta to choose the backfill path below.

## e. Backfill classification

**Backfill is TRIVIAL regardless of count.** The original
metadata payload at signup is **always `{}`** —
`auth_service.py:90` calls `grant_signup_grace(self.repo.db,
user_id=user.id)` with no metadata kwarg, and the default
parameter is `metadata: dict[str, Any] | None = None` which
the helper coerces to `_json_dumps({})`.

So the backfill is a single INSERT per affected user with:

  * `id = gen_random_uuid()`
  * `user_id = <affected user's id>`
  * `grant_type = 'signup_grace'`
  * `granted_at = <best estimate: user.created_at + small delta>`
  * `expires_at = NULL` for users past the 24h window, OR
    `granted_at + 24h` for very-recent signups
  * `metadata = '{}'`

**Choice of expires_at**: the original `signup_grace` window is
24 hours from grant. For users created days/weeks ago, the
24h-from-grant window is already over. Two options:

  * **(a) Backfill with expires_at = user.created_at + 24h.**
    Honest replication of what the grant would have produced.
    For users >24h old, the grant is already expired; they
    still see 402. Doesn't restore platform access.
  * **(b) Backfill with expires_at = NOW() + 24h.** Grants
    affected users 24h of access from the backfill moment.
    Restores the platform-access UX the regression broke.
    Slight stretch of the policy semantics (the grant was
    *meant* to fire at signup, not at backfill); arguably
    fair compensation for the regression.

**Recommendation: (b)** — restore the access the platform should
have provided. The bug took ~10 days of access from affected
users; granting 24h of access at backfill restores meaningful
free-trial UX. Per the original Pass 3f §C.4 abuse-prevention
clause, this is a one-time backfill, not an ongoing policy
shift.

## f. Recommended remediation

  1. **Syntax fix** (this commit): drop `::jsonb` at lines 677
     and 732 of `entitlement_service.py`. Postgres auto-casts.
  2. **Regression-guard test** (this commit): add a test that
     exercises `grant_signup_grace()` end-to-end with a real
     DB write, asserts the row lands successfully, asserts the
     metadata round-trips. Lives in
     `backend/tests/test_services/test_entitlement_grant_writes.py`.
  3. **Backfill script** (this commit, dry-run; founder
     executes for-real against production after running the
     count query): `backend/scripts/d_signup_grace_backfill.py`
     with `--dry-run` and `--apply` flags. Identifies affected
     users via the query above, INSERTs one row per affected
     user, logs an audit trail. Founder runs `--dry-run` first
     to verify counts match; then `--apply` once founder is
     satisfied.
  4. **Sentry fingerprint** (registered as a documentation
     item in `sentry-review-process.md` follow-up; founder
     configures in Sentry UI): pin `auth.signup_grace_failed`
     log entries to a known issue group so a regression
     surfaces immediately rather than getting lost in noise.

## Cross-references

- Companion path that already worked around the same bug:
  [`backend/app/agents/tools/agent_specific/billing_support/escalate_to_human.py`](../../backend/app/agents/tools/agent_specific/billing_support/escalate_to_human.py:181-200)
- Schema:
  [`backend/alembic/versions/0057_entitlement_tier.py`](../../backend/alembic/versions/0057_entitlement_tier.py)
- D18 surfacing:
  [`docs/followups/auth-signup-grace-jsonb-cast-syntax.md`](../followups/auth-signup-grace-jsonb-cast-syntax.md)
  (registered at D18 closure)
- D19.5 gate impact: Section 2 Item 2 of
  [`docs/architecture/d19-5-pre-launch-readiness-gate.md`](../architecture/d19-5-pre-launch-readiness-gate.md)
  moves from 🔴 RED to 🟢 GREEN once fix + tests land (this
  commit); backfill execution moves it to FULLY-RECONCILED
  once founder runs the script.
