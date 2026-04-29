/**
 * PR2/B5.3 — frontend request-timeout regression tests.
 *
 * Confirms that:
 *   1. A successful response below the timeout is returned normally.
 *   2. A response that takes longer than the timeout is aborted and
 *      surfaces as `ApiTimeoutError`, not as a hung promise.
 *   3. The error has a user-readable message — toast.error() can show
 *      `err.message` directly.
 *
 * We can't easily monkey-patch the 30s constant from outside without
 * exporting it, so the tests use a stub `fetch` that simulates the
 * race directly: the mocked fetch listens to `signal.abort` and rejects
 * with the same DOMException the browser would emit.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiTimeoutError, api } from "@/lib/api-client";

const realFetch = global.fetch;

beforeEach(() => {
  // Quiet the auth-refresh + token reads — they hit localStorage which
  // jsdom provides but we don't want noise.
  vi.stubGlobal("localStorage", {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  });
});

afterEach(() => {
  global.fetch = realFetch;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("api-client request timeout", () => {
  it("resolves normally when fetch returns before the timeout", async () => {
    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    const out = await api.get<{ ok: boolean }>("/api/v1/health/version");
    expect(out).toEqual({ ok: true });
  });

  it("throws ApiTimeoutError when fetch is aborted by the timeout", async () => {
    // Simulate a fetch that respects the AbortSignal — when aborted, it
    // rejects with a DOMException(name='AbortError'), exactly as the
    // browser does.
    global.fetch = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          const signal = init?.signal;
          if (!signal) return; // never resolves — would hang the test
          if (signal.aborted) {
            reject(new DOMException("aborted", "AbortError"));
            return;
          }
          signal.addEventListener("abort", () => {
            reject(new DOMException("aborted", "AbortError"));
          });
        }),
    ) as unknown as typeof fetch;

    // Trigger the abort by overriding setTimeout to fire immediately.
    const realSetTimeout = global.setTimeout;
    global.setTimeout = ((fn: () => void) => {
      fn();
      return 0 as unknown as ReturnType<typeof setTimeout>;
    }) as unknown as typeof setTimeout;

    try {
      await expect(api.get("/api/v1/anything")).rejects.toBeInstanceOf(
        ApiTimeoutError,
      );
    } finally {
      global.setTimeout = realSetTimeout;
    }
  });

  it("ApiTimeoutError message is user-readable", () => {
    const e = new ApiTimeoutError();
    expect(e.message.toLowerCase()).toContain("too long");
  });
});
