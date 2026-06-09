# CSP Enforcing Mode Cutover Plan

## Current State

`Content-Security-Policy-Report-Only` is live in both Next.js middleware and nginx.
All violations flow to `POST /api/v1/csp-report` and are logged via structlog.
No enforcement; no user-visible breakage.

## Cutover Prerequisites

Before switching to enforcing mode, all of the following must be resolved:

1. **Remove `'unsafe-inline'` from `script-src`**
   - Audit all inline `<script>` tags and `javascript:` handlers across the frontend.
   - Replace with nonce-based CSP (`nonce={nonce}`) injected from Next.js middleware, or
   - Hash-based allowlisting for static inline scripts.
   - Key blocker: Next.js 15 RSC hydration may inject inline scripts — test with nonce propagation first.

2. **Remove `'unsafe-eval'` from `script-src`**
   - Identify all `eval()`, `new Function()`, `setTimeout(string)` usage.
   - React 18+ and Next.js 15 do not require `eval` in production builds — likely only dev tools.

3. **Validate all external origins in `connect-src`**
   - `https://api.razorpay.com` — confirmed (payment gateway)
   - `https://*.sentry.io` — confirmed (error reporting)
   - Add any additional API domains that emerge from violation logs.

4. **2–4 weeks clean in production**
   - Zero new violation classes for 2 weeks in the structlog stream before enforcing.

## Cutover Steps

1. Collect all remaining violations from structlog. Group by `blocked-uri` and `violated-directive`.
2. For each: either add to the allowlist or fix the source to comply.
3. In `frontend/src/middleware.ts`: change `Content-Security-Policy-Report-Only` → `Content-Security-Policy`.
4. In `nginx/nginx.conf`: change `Content-Security-Policy-Report-Only` → `Content-Security-Policy`.
5. Keep `report-uri /api/v1/csp-report` — an enforcing CSP still reports violations.
6. Deploy to staging first. Monitor logs for 24 h. Then deploy to production.
7. Remove this followup doc once enforcing mode is stable.

## Rollback

If enforcing mode causes user-visible breakage, revert the header name in both files and redeploy. No schema change needed.
