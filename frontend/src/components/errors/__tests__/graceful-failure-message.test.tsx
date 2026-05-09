/**
 * D19.2 / CP1.5 — GracefulFailureMessage component tests.
 *
 * Mirrors route-error.test.tsx in shape but covers the inline
 * variant: trace_id surfacing, retry callback, default vs override
 * copy.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GracefulFailureMessage } from "@/components/errors/graceful-failure-message";

describe("GracefulFailureMessage", () => {
  it("renders the canonical D-C user_message by default", () => {
    render(<GracefulFailureMessage onRetry={() => {}} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByText(/something went wrong, please try again/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/we.*logged this/i)).toBeInTheDocument();
  });

  it("surfaces the trace_id as a Reference for support correlation", () => {
    const traceId = "0af7651916cd43dd8448eb211c80319c";
    render(<GracefulFailureMessage onRetry={() => {}} traceId={traceId} />);
    expect(
      screen.getByText(/if reporting this, mention reference/i),
    ).toBeInTheDocument();
    expect(screen.getByText(traceId)).toBeInTheDocument();
  });

  it("does not render the Reference block when traceId is missing", () => {
    render(<GracefulFailureMessage onRetry={() => {}} />);
    expect(
      screen.queryByText(/if reporting this, mention reference/i),
    ).not.toBeInTheDocument();
  });

  it("calls onRetry when Try again is clicked", () => {
    const onRetry = vi.fn();
    render(<GracefulFailureMessage onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("respects userMessage override when provided", () => {
    render(
      <GracefulFailureMessage
        onRetry={() => {}}
        userMessage="The mock interview couldn't start. Please try again."
      />,
    );
    expect(
      screen.getByText(/the mock interview couldn.*t start/i),
    ).toBeInTheDocument();
    // The default copy must NOT be present when override is set.
    expect(
      screen.queryByText(/something went wrong, please try again/i),
    ).not.toBeInTheDocument();
  });

  it("respects retryLabel override", () => {
    render(<GracefulFailureMessage onRetry={() => {}} retryLabel="Re-run" />);
    expect(screen.getByRole("button", { name: /re-run/i })).toBeInTheDocument();
  });
});
