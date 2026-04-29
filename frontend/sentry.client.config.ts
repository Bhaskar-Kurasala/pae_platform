/**
 * PR3/C4.1 — Sentry browser config.
 *
 * Loaded by `instrumentation-client.ts` in Next 15+. Mirrors the
 * design rules of the backend shim in `backend/app/core/sentry.py`:
 *
 *   1. **No-op safe.** When `NEXT_PUBLIC_SENTRY_DSN` is unset, init is
 *      a no-op. The `@sentry/nextjs` SDK already does this internally,
 *      but we belt-and-braces it here so a missing env var can't surface
 *      as a runtime error in dev.
 *
 *   2. **No PII by default.** `sendDefaultPii: false` keeps IPs and
 *      raw cookies out of the event. The backend already does the
 *      heavy PII filtering on its own events (see
 *      `backend/app/core/sentry.py::_before_send`).
 *
 *   3. **Conservative trace sampling.** 5% in prod, 0% in dev. The
 *      free tier is 5k errors/month — burning quota on transactions
 *      from local dev would be wasteful.
 *
 *   4. **Source maps deferred.** Production source-map upload requires
 *      a `SENTRY_AUTH_TOKEN` Fly secret + the `@sentry/nextjs` build-
 *      time wrapper in `next.config.ts`. That lands in the deploy PR
 *      (PR3/D7) when we actually have the secret in place. Until then,
 *      stack traces are minified — readable enough by line/col, just
 *      not by symbol.
 */

import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
const environment = process.env.NEXT_PUBLIC_SENTRY_ENV ?? "development";

if (dsn) {
  Sentry.init({
    dsn,
    environment,
    // 5% trace sampling in prod is the standard recommendation —
    // enough signal for perf debugging, not enough volume to fill a
    // free-tier project. Dev keeps it at 0 so debug noise stays out.
    tracesSampleRate: environment === "production" ? 0.05 : 0,
    // No replay session sampling at all — replay storage costs add up
    // fast on a free tier. We can opt in per-feature later via
    // `Sentry.startReplay()` from a specific page if needed.
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    sendDefaultPii: false,
    // Don't auto-instrument navigation as a transaction — the app
    // routes through Next App Router, not a SPA history.pushState
    // model, so the auto integration's spans aren't useful.
    integrations: [],
  });
}
