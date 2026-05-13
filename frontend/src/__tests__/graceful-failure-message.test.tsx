/**
 * CP2.4 / H4 — GracefulFailureMessage component smoke tests.
 *
 * Covers the four acceptance criteria for the inline error UX component:
 *   1. Default message renders when no userMessage prop is supplied.
 *   2. Custom userMessage overrides the default copy.
 *   3. onRetry is called when "Try again" is clicked.
 *   4. traceId appears in the DOM when provided.
 */

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GracefulFailureMessage } from "@/components/errors/graceful-failure-message";

// ---------------------------------------------------------------------------
// Sentry mock — prevents failures from missing DSN in test environment
// ---------------------------------------------------------------------------

vi.mock("@sentry/nextjs", () => ({
  captureException: vi.fn(),
  init: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GracefulFailureMessage", () => {
  it("renders the default 'Something went wrong' message when no userMessage is provided", () => {
    render(<GracefulFailureMessage onRetry={vi.fn()} />);

    expect(
      screen.getByText(/something went wrong/i)
    ).toBeTruthy();
  });

  it("renders the 'Try again' button by default", () => {
    render(<GracefulFailureMessage onRetry={vi.fn()} />);

    expect(
      screen.getByRole("button", { name: /try again/i })
    ).toBeTruthy();
  });

  it("renders custom userMessage text when provided", () => {
    render(
      <GracefulFailureMessage
        userMessage="Custom error text"
        onRetry={vi.fn()}
      />
    );

    expect(screen.getByText("Custom error text")).toBeTruthy();
  });

  it("does NOT render the default message when a custom userMessage is provided", () => {
    render(
      <GracefulFailureMessage
        userMessage="Custom error text"
        onRetry={vi.fn()}
      />
    );

    // Default copy must not appear alongside the custom message
    expect(screen.queryByText(/something went wrong/i)).toBeNull();
  });

  it("calls onRetry when the Try again button is clicked", () => {
    const onRetry = vi.fn();
    render(<GracefulFailureMessage onRetry={onRetry} />);

    const btn = screen.getByRole("button", { name: /try again/i });
    fireEvent.click(btn);

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders the traceId as a reference in the document when provided", () => {
    render(
      <GracefulFailureMessage traceId="abc123def" onRetry={vi.fn()} />
    );

    // The component renders traceId inside a <span class="select-all">
    expect(screen.getByText("abc123def")).toBeTruthy();
  });

  it("renders the role=alert accessibility attribute", () => {
    render(<GracefulFailureMessage onRetry={vi.fn()} />);

    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("does NOT render a reference block when traceId is not provided", () => {
    render(<GracefulFailureMessage onRetry={vi.fn()} />);

    // No "If reporting this, mention reference:" text should appear
    expect(screen.queryByText(/mention reference/i)).toBeNull();
  });
});
