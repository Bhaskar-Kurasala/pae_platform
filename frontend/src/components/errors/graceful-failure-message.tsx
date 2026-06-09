"use client";

/**
 * D19.2 / CP1.5 — GracefulFailureMessage.
 *
 * Inline (non-route-boundary) error UX for agent-invocation failures,
 * API timeouts, rate limits, and LLM-provider issues. Renders the
 * canonical D-C "try again" message + a small Reference ID block
 * (trace_id from the backend exception envelope) + a Try Again
 * button.
 *
 * Companion to RouteError (route-error.tsx) which handles Next.js
 * App Router boundary errors. The two share copy + visual language;
 * the difference is mount point:
 *
 *   - RouteError  — full-page boundary, replaces the route's render
 *   - GracefulFailureMessage — inline within a chat / interview /
 *     practice page, leaves the surrounding layout intact
 *
 * Usage:
 *
 *   // In a chat surface that just got a 503 from /agentic/default/chat:
 *   <GracefulFailureMessage
 *     traceId={errorBody.error?.trace_id ?? errorBody.error?.request_id}
 *     onRetry={() => retrySendMessage(input)}
 *   />
 *
 * The component is intentionally framework-agnostic — Tailwind utility
 * classes only, no design-token imports — so it renders gracefully
 * even when the surrounding screen has caught fire.
 */

import { useId } from "react";

interface GracefulFailureMessageProps {
  /** Optional W3C trace_id (preferred) or request_id from the backend
   *  error envelope. Surfaced as a Reference ID for support
   *  correlation. */
  traceId?: string | null;
  /** Optional override for the default message. Use sparingly — D-C
   *  is the canonical wording for almost every case. */
  userMessage?: string;
  /** Called when the user clicks Try Again. Required — the whole
   *  point of inline failure UX is letting the user re-attempt
   *  without losing their place. */
  onRetry: () => void;
  /** Optional className for the outer container so callers can adjust
   *  spacing inside their own surface (e.g., chat bubble vs panel). */
  className?: string;
  /** Optional override for the Try Again button label. */
  retryLabel?: string;
}

const DEFAULT_USER_MESSAGE =
  "Something went wrong, please try again. We've logged this and we're looking into it.";

export function GracefulFailureMessage({
  traceId,
  userMessage,
  onRetry,
  className,
  retryLabel = "Try again",
}: GracefulFailureMessageProps) {
  const headingId = useId();
  const message = userMessage?.trim() || DEFAULT_USER_MESSAGE;
  return (
    <div
      role="alert"
      aria-labelledby={headingId}
      aria-live="polite"
      className={
        "rounded-lg border border-destructive/30 bg-destructive/5 p-4 " +
        "flex flex-col gap-3 " +
        (className ?? "")
      }
    >
      <p id={headingId} className="text-sm text-foreground leading-relaxed">
        {message}
      </p>
      {traceId ? (
        <p className="text-xs text-muted-foreground font-mono">
          If reporting this, mention reference:{" "}
          <span className="select-all">{traceId}</span>
        </p>
      ) : null}
      <div>
        <button
          type="button"
          onClick={onRetry}
          className={
            "h-8 rounded-lg bg-primary px-3 text-sm font-medium " +
            "text-primary-foreground transition hover:bg-primary/90"
          }
        >
          {retryLabel}
        </button>
      </div>
    </div>
  );
}
