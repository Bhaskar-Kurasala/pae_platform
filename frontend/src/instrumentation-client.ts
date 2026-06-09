/**
 * PR3/C4.1 — Next.js client-side instrumentation entry.
 *
 * Next 15.3+ auto-loads this file in the browser bundle before any
 * page renders, so Sentry's beforeNavigate hooks can attach. We just
 * re-export the side-effects of `sentry.client.config.ts`.
 *
 * https://nextjs.org/docs/app/api-reference/file-conventions/instrumentation-client
 */

import "../sentry.client.config";

export const onRouterTransitionStart = (): void => {
  // Hook reserved for future Sentry navigation transactions; today
  // we keep tracesSampleRate=0 outside production, so this is a
  // no-op. Defining the export silences the Next "missing transition
  // hook" advisory in the build log.
};
