/**
 * PR3/C4.1 — Sentry Node.js (Next server runtime) config.
 *
 * Captures errors thrown in route handlers, server components, and
 * `getServerSideProps`-equivalents. The backend FastAPI app has its
 * own Sentry init in `backend/app/core/sentry.py` — this file is for
 * the Next.js BFF / SSR layer specifically.
 *
 * Same no-op-safe design as the client config. We use the same
 * NEXT_PUBLIC_SENTRY_DSN so client + server events land in the same
 * Sentry project (separate runtimes are tagged as such by the SDK).
 */

import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
const environment = process.env.NEXT_PUBLIC_SENTRY_ENV ?? "development";

if (dsn) {
  Sentry.init({
    dsn,
    environment,
    tracesSampleRate: environment === "production" ? 0.05 : 0,
    sendDefaultPii: false,
    // No console-breadcrumb auto-instrumentation — Next server logs
    // are noisy enough that they'd drown the actual error context.
    integrations: [],
  });
}
