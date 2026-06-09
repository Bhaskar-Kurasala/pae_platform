"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect, useState } from "react";

import { GracefulFailureMessage } from "@/components/errors/graceful-failure-message";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api-client";

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

type ReportView = "idle" | "form" | "sending" | "done" | "error";

export default function ErrorPage({ error, reset }: ErrorPageProps) {
  const [view, setView] = useState<ReportView>("idle");
  const [body, setBody] = useState("");

  useEffect(() => {
    console.error("[app/error]", error);
    try {
      Sentry.captureException(error);
    } catch {
      // Sentry may not be configured (no DSN) — swallow silently
    }
  }, [error]);

  const submitReport = async () => {
    setView("sending");
    try {
      await api.post("/api/v1/feedback", {
        route: window.location.pathname,
        body,
        category: "bug",
        // error.tsx fires only on real exceptions, so default severity is
        // "blocking" — a thrown error already blocked the student's flow.
        severity: "blocking",
        url: window.location.href,
        user_agent: navigator.userAgent,
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
        app_version: process.env.NEXT_PUBLIC_APP_VERSION ?? "",
        error_id: error.digest ?? "",
        sentiment: "negative",
      });
      setView("done");
    } catch {
      setView("error");
    }
  };

  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center p-6 gap-6">
      <GracefulFailureMessage
        traceId={error.digest ?? null}
        userMessage="Something went wrong. We've been notified and are looking into it."
        onRetry={reset}
        retryLabel="Try again"
      />

      <div className="w-full max-w-md">
        {view === "idle" ? (
          <div className="flex justify-center">
            <Button variant="outline" onClick={() => setView("form")}>
              Tell us what happened
            </Button>
          </div>
        ) : null}

        {(view === "form" || view === "sending") && (
          <div className="flex flex-col gap-3 rounded-lg border border-border bg-background p-4">
            <label
              htmlFor="error-report-body"
              className="text-sm font-medium text-foreground"
            >
              What were you trying to do?
            </label>
            <textarea
              id="error-report-body"
              className="min-h-[96px] w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
              placeholder="What were you trying to do? (We'll attach the error trace automatically.)"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              disabled={view === "sending"}
            />
            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                onClick={() => {
                  setView("idle");
                  setBody("");
                }}
                disabled={view === "sending"}
              >
                Cancel
              </Button>
              <Button
                onClick={submitReport}
                loading={view === "sending"}
                disabled={body.trim().length === 0}
              >
                Send
              </Button>
            </div>
          </div>
        )}

        {view === "done" ? (
          <p className="text-center text-sm text-muted-foreground">
            Thanks — we&apos;ll take a look.
          </p>
        ) : null}

        {view === "error" ? (
          <div className="flex flex-col items-center gap-2">
            <p className="text-center text-sm text-destructive">
              Couldn&apos;t send report. Sorry.
            </p>
            <Button variant="ghost" onClick={() => setView("form")}>
              Try again
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
