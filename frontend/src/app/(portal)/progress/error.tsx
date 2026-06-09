"use client";

import { RouteError } from "@/components/errors/route-error";

export default function ProgressError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError error={error} reset={reset} />;
}
