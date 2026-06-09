"use client";

import { RouteError } from "@/components/errors/route-error";

/**
 * Public route-group error boundary (PR2/B3.1). Sends the user to the
 * landing page rather than the portal home — they may not be logged in.
 */
export default function PublicError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError error={error} reset={reset} homeHref="/" homeLabel="Back to home" />;
}
