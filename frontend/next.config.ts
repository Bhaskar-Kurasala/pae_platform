import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  output: "standalone",
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8080/api/:path*",
      },
    ];
  },
};

/**
 * PR3/D7 — Sentry build wrapper.
 *
 * `withSentryConfig` does two jobs:
 *   1. Wires the runtime SDK init files (sentry.{client,server,edge}.config.ts)
 *      that PR3/C4 added so they actually load in the bundle.
 *   2. Optionally uploads source maps to Sentry at build time so stack
 *      traces in the issues board map back to TypeScript source instead
 *      of minified JS.
 *
 * Source-map upload only runs when `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, and
 * `SENTRY_PROJECT` are all in the environment — usually only in CI / Fly
 * production builds. Local `pnpm build` and CI without secrets configured
 * skip the upload silently and ship minified maps; that's the design
 * intent (we don't want every preview deploy hitting our Sentry quota).
 *
 * `silent: true` keeps the build log readable when the wrapper has
 * nothing to do; flip to false locally if you're debugging a missing
 * upload.
 */
const sentryEnabled = !!(
  process.env.SENTRY_AUTH_TOKEN &&
  process.env.SENTRY_ORG &&
  process.env.SENTRY_PROJECT
);

export default withSentryConfig(nextConfig, {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  silent: true,
  // Skip source-map upload entirely when auth credentials are missing.
  // The wrapper still wires the runtime SDK init either way — this
  // gate only governs whether maps actually upload to Sentry.
  sourcemaps: {
    disable: !sentryEnabled,
  },
});
