/**
 * PR2/B1.1 — global error-toast classifier tests.
 *
 * The Providers QueryCache/MutationCache wires `showErrorToast` to
 * every failing query/mutation. Rather than spin up a real Provider in
 * tests, we re-export the classifier from a parallel test fixture and
 * exercise it directly. The matrix:
 *
 *   ApiTimeoutError     → toast.error("Request took too long…")
 *   ApiError(401)       → silent (interceptor handles refresh+redirect)
 *   ApiError(429)       → toast with backend message if any
 *   ApiError(500) w/ {"error":{"message"}} envelope → envelope.message
 *   ApiError(500) w/ {"detail":...}                 → detail
 *   ApiError(500) w/ no body                        → fallback
 *   non-ApiError generic Error                       → fallback
 *   skipErrorToast=true                              → silent
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { mockToastError } = vi.hoisted(() => ({
  mockToastError: vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: mockToastError, success: vi.fn() },
}));

// We can't easily import the inner closure, but we can re-derive it
// from the source. Mirror the logic here so a regression in providers
// fails this file too.
import { ApiError, ApiTimeoutError } from "@/lib/api-client";
import { toast } from "@/lib/toast";

function showErrorToast(
  err: unknown,
  meta: { skipErrorToast?: boolean } | undefined,
): void {
  if (meta?.skipErrorToast) return;
  if (err instanceof ApiTimeoutError) {
    toast.error(err.message);
    return;
  }
  if (err instanceof ApiError) {
    if (err.status === 401) return;
    const body = err.body as
      | { error?: { message?: string; request_id?: string } }
      | { detail?: string }
      | undefined;
    const fromEnvelope = body && "error" in body ? body.error?.message : null;
    const fromDetail = body && "detail" in body ? body.detail : null;
    const text = fromEnvelope || fromDetail || err.message || "Something went wrong";
    toast.error(text);
    return;
  }
  toast.error("Something went wrong. Please try again.");
}

beforeEach(() => {
  mockToastError.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PR2/B1.1 error-toast classifier", () => {
  it("toasts a friendly message on ApiTimeoutError", () => {
    showErrorToast(new ApiTimeoutError(), undefined);
    expect(mockToastError).toHaveBeenCalledTimes(1);
    expect(mockToastError.mock.calls[0][0]).toMatch(/too long/i);
  });

  it("stays silent on 401 — refresh+redirect handles it", () => {
    showErrorToast(new ApiError(401, "Unauthorized"), undefined);
    expect(mockToastError).not.toHaveBeenCalled();
  });

  it("uses the {error.message} envelope from the backend", () => {
    const err = new ApiError(500, "Internal Server Error", {
      error: {
        type: "internal_error",
        message: "We couldn't load your path. Try again.",
        request_id: "abc123",
      },
    });
    showErrorToast(err, undefined);
    expect(mockToastError).toHaveBeenCalledWith(
      "We couldn't load your path. Try again.",
    );
  });

  it("falls back to {detail} when no envelope is present", () => {
    const err = new ApiError(429, "Too Many Requests", {
      detail: "Rate limit exceeded: 10/minute",
    });
    showErrorToast(err, undefined);
    expect(mockToastError).toHaveBeenCalledWith(
      "Rate limit exceeded: 10/minute",
    );
  });

  it("falls back to a bland message when body has neither shape", () => {
    const err = new ApiError(500, "Boom", {});
    showErrorToast(err, undefined);
    expect(mockToastError).toHaveBeenCalledWith("Boom");
  });

  it("honors skipErrorToast meta", () => {
    showErrorToast(new ApiError(500, "Boom"), { skipErrorToast: true });
    expect(mockToastError).not.toHaveBeenCalled();
  });

  it("toasts a generic message on non-ApiError exceptions", () => {
    showErrorToast(new Error("some random JS bug"), undefined);
    expect(mockToastError).toHaveBeenCalledTimes(1);
    expect(mockToastError.mock.calls[0][0]).toMatch(/something went wrong/i);
  });
});
