"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

import { GracefulFailureMessage } from "@/components/errors/graceful-failure-message";

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function ErrorPage({ error, reset }: ErrorPageProps) {
  useEffect(() => {
    console.error("[app/error]", error);
    try {
      Sentry.captureException(error);
    } catch {
      // Sentry may not be configured (no DSN) — swallow silently
    }
  }, [error]);

  return (
    <div className="min-h-[60vh] flex items-center justify-center p-6">
      <GracefulFailureMessage
        traceId={error.digest ?? null}
        userMessage="Something went wrong. We've been notified and are looking into it."
        onRetry={reset}
        retryLabel="Try again"
      />
    </div>
  );
}
