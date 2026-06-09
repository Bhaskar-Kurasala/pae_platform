"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

interface GlobalErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({ error, reset }: GlobalErrorProps) {
  useEffect(() => {
    console.error("[app/global-error]", error);
    try {
      Sentry.captureException(error);
    } catch {
      // Sentry may not be configured (no DSN) — swallow silently
    }
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          padding: 0,
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
          backgroundColor: "#F8FAFC",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "100vh",
        }}
      >
        <div
          style={{
            backgroundColor: "#FFFFFF",
            border: "1px solid #E5E7EB",
            borderRadius: "12px",
            padding: "40px 32px",
            maxWidth: "440px",
            width: "100%",
            margin: "16px",
            textAlign: "center",
          }}
        >
          <h1
            style={{
              margin: "0 0 8px",
              fontSize: "20px",
              fontWeight: 600,
              color: "#111827",
            }}
          >
            Something went wrong
          </h1>

          <p
            style={{
              margin: "0 0 16px",
              fontSize: "14px",
              color: "#6B7280",
              lineHeight: 1.6,
            }}
          >
            We&rsquo;ve been notified and are looking into it.
          </p>

          {error.digest ? (
            <p
              style={{
                margin: "0 0 24px",
                fontSize: "12px",
                color: "#6B7280",
                fontFamily: "monospace",
              }}
            >
              Reference: <span style={{ userSelect: "all" }}>{error.digest}</span>
            </p>
          ) : (
            <div style={{ marginBottom: "24px" }} />
          )}

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "10px",
              alignItems: "center",
            }}
          >
            <button
              type="button"
              onClick={reset}
              style={{
                width: "100%",
                maxWidth: "280px",
                padding: "10px 20px",
                borderRadius: "8px",
                border: "none",
                backgroundColor: "#1D9E75",
                color: "#FFFFFF",
                fontSize: "14px",
                fontWeight: 500,
                cursor: "pointer",
              }}
            >
              Try again
            </button>

            <button
              type="button"
              onClick={() => window.location.reload()}
              style={{
                width: "100%",
                maxWidth: "280px",
                padding: "10px 20px",
                borderRadius: "8px",
                border: "1px solid #D1D5DB",
                backgroundColor: "#FFFFFF",
                color: "#111827",
                fontSize: "14px",
                fontWeight: 500,
                cursor: "pointer",
              }}
            >
              Reload page
            </button>

            <a
              href="/"
              style={{
                marginTop: "4px",
                fontSize: "14px",
                color: "#1D9E75",
                textDecoration: "underline",
              }}
            >
              Go to home
            </a>
          </div>
        </div>
      </body>
    </html>
  );
}
