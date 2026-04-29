/**
 * PR2/B3.1 — RouteError component tests.
 *
 * Confirms the branded fallback shows the right copy, exposes the
 * digest for support, fires `reset` on click, and renders the dev-only
 * stack-trace block.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { RouteError } from "@/components/errors/route-error";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: React.ComponentProps<"a">) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RouteError", () => {
  it("renders the calm branded headline + body", () => {
    const err = new Error("kaboom");
    render(<RouteError error={err} reset={() => {}} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/we hit an unexpected error/i)).toBeInTheDocument();
    expect(screen.getByText(/we.*logged this/i)).toBeInTheDocument();
  });

  it("surfaces the error digest as a Reference id", () => {
    const err = Object.assign(new Error("oops"), { digest: "abcdef-12345" });
    render(<RouteError error={err} reset={() => {}} />);
    expect(screen.getByText(/abcdef-12345/)).toBeInTheDocument();
  });

  it("calls reset() when Try again is clicked", () => {
    const reset = vi.fn();
    render(<RouteError error={new Error("x")} reset={reset} />);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("uses the custom homeHref + homeLabel when provided", () => {
    render(
      <RouteError
        error={new Error("x")}
        reset={() => {}}
        homeHref="/admin"
        homeLabel="Back to dashboard"
      />,
    );
    const home = screen.getByRole("link", { name: /back to dashboard/i });
    expect(home).toHaveAttribute("href", "/admin");
  });

  it("renders the stack trace details block in dev", () => {
    const err = new Error("with stack");
    err.stack = "Error: with stack\n    at someplace.tsx:42";
    render(<RouteError error={err} reset={() => {}} />);
    // <details> is open=false by default; we just check it exists with
    // the right content.
    expect(screen.getByText(/at someplace\.tsx:42/)).toBeInTheDocument();
  });
});
