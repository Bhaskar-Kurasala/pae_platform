/**
 * PR2/B1.1 + PR3/C1.1 — global error-toast classifier tests.
 *
 * The Providers QueryCache/MutationCache wires `showErrorToast` to
 * every failing query/mutation. We import the REAL function from
 * `@/lib/error-toast` so a regression there shows up here.
 *
 * Buckets (PR2/B1.1):
 *   ApiTimeoutError     → toast.error("Request took too long…")
 *   ApiError(401)       → silent (interceptor handles refresh+redirect)
 *   ApiError(429)       → toast with backend message if any
 *   ApiError(500) w/ {"error":{"message"}} envelope → envelope.message
 *   ApiError(500) w/ {"detail":...}                 → detail
 *   ApiError(500) w/ no body                        → fallback
 *   non-ApiError generic Error                       → fallback
 *   skipErrorToast=true                              → silent
 *
 * Reference suffix (PR3/C1.1):
 *   Every fired toast ends with "Reference: <8-char-id>" when a
 *   request_id is available. We mock getLastRequestId so the
 *   module-scope fallback doesn't leak between tests.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { mockToastError, mockGetLastRequestId } = vi.hoisted(() => ({
  mockToastError: vi.fn(),
  mockGetLastRequestId: vi.fn<() => string | null>(),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: mockToastError, success: vi.fn() },
}));

vi.mock("@/lib/api-client", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api-client")>(
      "@/lib/api-client",
    );
  return {
    ...actual,
    // Re-export the real classes; only stub the request-id getter.
    getLastRequestId: mockGetLastRequestId,
  };
});

import { ApiError, ApiTimeoutError } from "@/lib/api-client";
import { showErrorToast } from "@/lib/error-toast";

beforeEach(() => {
  mockToastError.mockReset();
  mockGetLastRequestId.mockReset();
  mockGetLastRequestId.mockReturnValue(null);
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
        request_id: "abc12345-aaaa-bbbb-cccc-dddddddddddd",
      },
    });
    showErrorToast(err, undefined);
    // Message + reference suffix.
    expect(mockToastError).toHaveBeenCalledTimes(1);
    const msg = mockToastError.mock.calls[0][0] as string;
    expect(msg).toContain("We couldn't load your path. Try again.");
    expect(msg).toContain("Reference: abc12345");
  });

  it("falls back to {detail} when no envelope is present", () => {
    const err = new ApiError(429, "Too Many Requests", {
      detail: "Rate limit exceeded: 10/minute",
    });
    showErrorToast(err, undefined);
    const msg = mockToastError.mock.calls[0][0] as string;
    expect(msg).toContain("Rate limit exceeded: 10/minute");
  });

  it("falls back to a bland message when body has neither shape", () => {
    const err = new ApiError(500, "Boom", {});
    showErrorToast(err, undefined);
    const msg = mockToastError.mock.calls[0][0] as string;
    expect(msg).toContain("Boom");
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

describe("PR3/C1.1 reference-suffix on toasts", () => {
  it("appends Reference: <short-id> when ApiError carries a requestId", () => {
    const err = new ApiError(
      500,
      "Boom",
      undefined,
      "deadbeef-1111-2222-3333-444455556666",
    );
    showErrorToast(err, undefined);
    const msg = mockToastError.mock.calls[0][0] as string;
    expect(msg).toContain("Reference: deadbeef");
  });

  it("falls back to getLastRequestId() on non-ApiError paths (timeouts)", () => {
    mockGetLastRequestId.mockReturnValue(
      "cafef00d-0000-0000-0000-000000000000",
    );
    showErrorToast(new ApiTimeoutError(), undefined);
    const msg = mockToastError.mock.calls[0][0] as string;
    expect(msg).toContain("Reference: cafef00d");
  });

  it("does NOT append a reference line when no id is available anywhere", () => {
    mockGetLastRequestId.mockReturnValue(null);
    showErrorToast(new ApiError(500, "Boom"), undefined);
    const msg = mockToastError.mock.calls[0][0] as string;
    expect(msg).not.toContain("Reference:");
  });

  it("prefers err.requestId over the envelope's request_id (most accurate)", () => {
    // Both id sources present — `err.requestId` came from the response
    // header, the envelope id came from the JSON body. They should
    // match in practice; if they ever drift, the per-error one wins.
    const err = new ApiError(
      500,
      "Boom",
      {
        error: {
          message: "Boom",
          request_id: "envelope-id-different-aaaaaaaaaaaaaaaaaaaaaaaa",
        },
      },
      "header-id-wins-bbbbbbbbbbbbbbbbbbbbbbbb",
    );
    showErrorToast(err, undefined);
    const msg = mockToastError.mock.calls[0][0] as string;
    expect(msg).toContain("Reference: headerid");
    expect(msg).not.toContain("Reference: envelope");
  });
});
