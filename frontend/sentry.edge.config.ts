/**
 * PR3/C4.1 — Sentry Edge runtime config.
 *
 * Next.js middleware and any route handlers running on the Edge
 * runtime use this config. We don't currently have any edge routes,
 * but the file is required by the Sentry Next.js integration when
 * the build wrapper is in place — keeping it as a no-op-safe stub
 * means we don't have to remember to add it later.
 */

import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: 0,
    sendDefaultPii: false,
    integrations: [],
  });
}
