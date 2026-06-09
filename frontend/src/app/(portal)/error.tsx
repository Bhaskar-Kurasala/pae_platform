"use client";

import { RouteError } from "@/components/errors/route-error";

/**
 * Portal-wide error boundary. Catches any uncaught render exception in
 * any (portal) route and shows the branded fallback. PR2/B3.1.
 */
export default function PortalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError error={error} reset={reset} />;
}
