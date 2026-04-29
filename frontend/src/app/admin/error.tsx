"use client";

import { RouteError } from "@/components/errors/route-error";

/**
 * Admin error boundary (PR2/B3.1). Sends admins back to the dashboard
 * home instead of /today since they may not have a student profile.
 */
export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <RouteError
      error={error}
      reset={reset}
      homeHref="/admin"
      homeLabel="Back to dashboard"
    />
  );
}
