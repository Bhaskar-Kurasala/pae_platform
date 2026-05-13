# OAuth state parameter CSRF validation gap

**Registered:** 2026-05-13 (Batch 1 Auth pre-flight, D6)
**Severity:** MEDIUM
**Status:** Deferred — not in scope for Batch 1

## What was found

During Batch 1 CP1 pre-flight audit of `backend/app/api/v1/routes/oauth.py`:

- Both the GitHub and Google OAuth flows generate a `state` parameter at
  authorization initiation (`secrets.token_urlsafe(16)`) but **do not
  validate the state on the callback**.
- The callback handlers (`github_callback`, `google_callback`) accept
  `state: str = Query(default="")` but never compare it to the value
  generated at initiation.
- This is a classic OAuth CSRF vector: an attacker can initiate the flow
  with their own `code` and a crafted redirect, and if the state is not
  validated the callback handler will process it.

## Why deferred

- OAuth signup currently requires GitHub/Google credentials the attacker
  would need to control — the CSRF attack surface is limited in the
  current user population.
- State validation requires session or Redis storage to persist the
  generated value between the initiation redirect and the callback.
  This is a non-trivial addition; adding a Redis-backed state store
  mid-Batch-1 would expand CP2 scope and delay the launch-blocker items
  (A1–A4, A14, A16, G1, G6).
- Cohort-1 launch is founder-invite-only; OAuth provider credential
  requirements are a meaningful attacker barrier at this scale.

## Recommended fix (cohort-2 scope)

1. On `/auth/oauth/{provider}` initiation, generate state and store it
   in Redis with a short TTL (10 minutes):
   `namespaced_key("oauth_state", state_value)` → `SET … EX 600`
2. On the callback, retrieve and delete the Redis key:
   - If missing or value mismatch → reject with 400 Bad Request.
   - This is a one-shot check (DELETE on retrieve = consumed token).
3. Alternatively, sign the state with HMAC using `settings.secret_key`
   (stateless validation — no Redis required).

## Re-evaluation trigger

- Cohort-2 onboarding planning (OAuth becomes higher volume)
- Any OAuth-related incident or reported anomaly
- Any expansion of OAuth provider support (LinkedIn, GitLab, etc.)

## Related

- `oauth.py:108` (GitHub state generation)
- `oauth.py:224` (Google state generation)
- Pattern 22 (always-verify) — this gap was caught via pre-flight audit,
  not production incident. Pre-flight is working as designed.
