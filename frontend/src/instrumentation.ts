/**
 * PR3/C4.1 — Next.js server-side instrumentation entry.
 *
 * Next 15+ auto-discovers this file and runs `register()` exactly
 * once on server startup (Node and Edge runtimes both). We use it as
 * the single chokepoint for both Sentry inits — the file dispatch
 * keeps the Edge bundle from importing Node-only code.
 *
 * https://nextjs.org/docs/app/api-reference/file-conventions/instrumentation
 */

export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("../sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("../sentry.edge.config");
  }
}
