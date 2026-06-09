# Followup: Dedicated /auth/verify-email/resend endpoint

**Registered:** 2026-05-14  
**Source:** Batch 1 CP2 closure note  
**Priority:** Batch 2

## What was deferred

The verify-email resend page (`frontend/src/app/(public)/verify-email/resend/page.tsx`) currently calls `requestPasswordReset(email)` as a placeholder because no dedicated resend endpoint exists.

This is a UX gap: users who land on `/verify-email/resend?email=...` after a 403 "not verified" login get a reset-password email rather than a verification email. Functional but confusing.

## What needs to be built

**Backend:** `POST /api/v1/auth/verify-email/resend`
```json
Request:  { "email": "user@example.com" }
Response: 202 { "message": "..." }  // always neutral
```

Logic:
1. Look up user by email — if not found, return 202 (no enumeration)
2. If already verified, send account_exists email, return 202
3. If unverified: check email rate limit (same `check_email_rate_limit` mechanism), create new `email_verify` token, send verification email, return 202

**Frontend:** Update `verify-email/resend/page.tsx` to call `authApi.resendVerificationEmail(email)` instead of `requestPasswordReset`.

**Test:** Add to `test_auth_token_service.py` — resend for unverified user creates new token; resend for already-verified user returns 202 without creating token.

## Notes

- Rate-limited to 5/hour per user via the existing `check_email_rate_limit` mechanism
- The `email_verify` TOKEN_TTL is 24h — a new token replaces the old one (old token is still valid until it expires, which is fine since tokens are single-use)
- Should be added to Section 2.4 of the production-readiness-test-tracker when implemented
