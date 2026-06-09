"use client";

/**
 * PR2/B3.1 + PR3/C3.2 — branded route-level error boundary.
 *
 * Drop-in for Next.js App Router `error.tsx` files. Replaces the
 * default white-screen-with-stack-trace with:
 *   - A calm, branded message that doesn't shout at the student.
 *   - The X-Request-ID surfaced so support can find the trace in logs.
 *   - A "Try again" button (calls `reset()` from the App Router
 *     boundary protocol) and a "Go to Today" escape hatch.
 *   - A subtle dev-only `<details>` block carrying the stack trace
 *     so engineers debugging locally still get the info.
 *   - PR3/C3.2: fires an `error.boundary_caught` event so PostHog
 *     can surface a "users hitting the boundary" panel and the
 *     on-call dashboard can correlate with backend Sentry events.
 *
 * The component is intentionally framework-agnostic — it doesn't pull
 * in v8 design tokens directly; it leans on the same Tailwind classes
 * the rest of the app uses so it renders gracefully even when the
 * surrounding screen has caught fire.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { trackErrorBoundaryCaught } from "@/lib/analytics-events";

interface RouteErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
  /** Optional — overrides the default home button target. */
  homeHref?: string;
  homeLabel?: string;
}

export function RouteError({
  error,
  reset,
  homeHref = "/today",
  homeLabel = "Back to Today",
}: RouteErrorProps) {
  const pathname = usePathname();

  useEffect(() => {
    // PR3/C4: Sentry now auto-captures uncaught errors via the SDK
    // when configured (no-op without DSN). Keeping the dev-mode
    // console.error so engineers debugging locally still see the
    // cause without staring at PostHog.
    if (typeof window !== "undefined") {
      console.error("[route-error]", error);
    }
    // PR3/C3.2 — emit a structured event so PostHog can surface a
    // "users hitting the boundary" panel. Fire once per render of
    // this boundary; React effects + a stable error object keep the
    // dependency list clean.
    trackErrorBoundaryCaught({
      digest: error.digest,
      pathname: pathname ?? "unknown",
    });
  }, [error, pathname]);

  // Next.js attaches a `digest` to server-rendered errors that pairs
  // with the structured log line — surface it like a request ID so
  // support can correlate.
  const reference = error.digest ?? null;

  return (
    <div
      role="alert"
      aria-live="polite"
      className="min-h-[60vh] flex flex-col items-center justify-center gap-6 px-6 py-12 text-center"
    >
      <div className="max-w-md flex flex-col items-center gap-3">
        <div className="rounded-full border border-destructive/30 bg-destructive/5 px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-destructive">
          Something broke
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          We hit an unexpected error.
        </h1>
        <p className="text-sm text-muted-foreground leading-relaxed">
          We&rsquo;ve logged this and you can carry on. Try the action again, or
          head back to your home screen.
        </p>
        {reference ? (
          <p className="text-xs text-muted-foreground font-mono">
            Reference: <span className="select-all">{reference}</span>
          </p>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:bg-primary/90"
        >
          Try again
        </button>
        <Link
          href={homeHref}
          className="h-9 inline-flex items-center rounded-lg border border-border bg-background px-4 text-sm font-medium text-foreground transition hover:bg-muted"
        >
          {homeLabel}
        </Link>
      </div>

      {process.env.NODE_ENV !== "production" ? (
        <details className="mt-4 max-w-2xl text-left text-xs text-muted-foreground">
          <summary className="cursor-pointer">Stack trace (dev only)</summary>
          <pre className="mt-2 whitespace-pre-wrap rounded bg-muted/30 p-3 font-mono text-[11px] leading-relaxed">
            {error.stack || error.message || "(no stack)"}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
