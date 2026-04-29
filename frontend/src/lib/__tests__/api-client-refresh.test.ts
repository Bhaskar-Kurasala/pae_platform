/**
 * PR2/B2.1 — token refresh interceptor regression tests.
 *
 * The api-client has had a refresh interceptor for a while; this test
 * pins down its contract so a future refactor can't quietly break it.
 *
 *   - On 401 with an existing access token, the helper attempts ONE
 *     silent refresh against /api/v1/auth/refresh.
 *   - If the refresh succeeds, the original request is retried with
 *     the fresh token.
 *   - If the refresh fails, the user is redirected to /login (we
 *     verify the storage clear; the redirect itself is jsdom-side and
 *     hard to assert cleanly).
 *   - The /auth/refresh endpoint itself never recurses — a 401 from
 *     refresh does NOT trigger another refresh.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api-client";

const realFetch = global.fetch;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const STORAGE = new Map<string, string>();

beforeEach(() => {
  STORAGE.clear();
  STORAGE.set(
    "auth-storage",
    JSON.stringify({
      state: {
        token: "stale-token",
        refreshToken: "valid-refresh",
        isAuthenticated: true,
      },
    }),
  );
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => STORAGE.get(k) ?? null,
    setItem: (k: string, v: string) => {
      STORAGE.set(k, v);
    },
    removeItem: (k: string) => {
      STORAGE.delete(k);
    },
  });
});

afterEach(() => {
  global.fetch = realFetch;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PR2/B2.1 token refresh interceptor", () => {
  it("retries the original request after a successful silent refresh", async () => {
    const calls: { url: string; auth: string | null }[] = [];

    global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>;
      const auth = headers["Authorization"] ?? null;
      calls.push({ url, auth });

      if (url.endsWith("/api/v1/auth/refresh")) {
        return jsonResponse(200, {
          access_token: "fresh-token",
          refresh_token: "valid-refresh",
        });
      }
      if (auth === "Bearer stale-token") {
        return jsonResponse(401, { detail: "expired" });
      }
      if (auth === "Bearer fresh-token") {
        return jsonResponse(200, { ok: true });
      }
      return jsonResponse(500, { detail: "unexpected" });
    }) as unknown as typeof fetch;

    const out = await api.get<{ ok: boolean }>("/api/v1/today/summary");

    expect(out).toEqual({ ok: true });
    // First request stale, refresh, second request fresh.
    expect(calls[0].auth).toBe("Bearer stale-token");
    expect(calls[1].url).toContain("/auth/refresh");
    expect(calls[2].auth).toBe("Bearer fresh-token");
  });

  it(
    "does NOT recurse on a 401 from /auth/refresh itself",
    async () => {
      let refreshCalls = 0;
      let mainCalls = 0;
      global.fetch = vi.fn(async (url: string) => {
        if (url.endsWith("/api/v1/auth/refresh")) {
          refreshCalls += 1;
          return jsonResponse(401, { detail: "expired refresh" });
        }
        mainCalls += 1;
        return jsonResponse(401, { detail: "expired" });
      }) as unknown as typeof fetch;

      // After both 401s the api-client clears storage and calls
      // location.replace; the awaited promise never resolves by design.
      // Race against a 1-second sentinel so the test doesn't hang on
      // that intentional non-resolution.
      const result = await Promise.race([
        api.get("/api/v1/today/summary").catch(() => "rejected"),
        new Promise((r) => setTimeout(() => r("timed_out"), 1000)),
      ]);

      // Storage was cleared by the api-client redirect path.
      expect(STORAGE.get("auth-storage")).toBeUndefined();
      // Refresh was hit AT MOST once — no recursion.
      expect(refreshCalls).toBeLessThanOrEqual(1);
      // Main route hit at most twice (initial + retry attempt).
      expect(mainCalls).toBeLessThanOrEqual(2);
      // We expect non-resolution since the redirect is in-flight.
      expect(result).toBe("timed_out");
    },
    7000,
  );
});
