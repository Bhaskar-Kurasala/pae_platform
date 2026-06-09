/**
 * PR3/C1.1 — frontend X-Request-ID capture regression tests.
 *
 * Confirms that:
 *   1. A successful response writes its X-Request-ID into the
 *      module-scoped `lastRequestId` so toasts on later non-ApiError
 *      paths (timeouts, network blips) can still cite a trace.
 *   2. A response with no X-Request-ID does NOT clobber the previous
 *      value (we only update when we got a fresh one).
 *   3. An error response stamps `requestId` onto the thrown ApiError
 *      so the toast classifier can prefer the per-error id over the
 *      module-scoped one.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, getLastRequestId } from "@/lib/api-client";

const realFetch = global.fetch;

beforeEach(() => {
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

describe("api-client X-Request-ID capture (PR3/C1.1)", () => {
  it("captures X-Request-ID off a successful response into getLastRequestId()", async () => {
    global.fetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": "abc12345-6789-fedc-ba98-7654321fedcb",
          },
        }),
    ) as unknown as typeof fetch;

    await api.get("/api/v1/anything");
    expect(getLastRequestId()).toBe("abc12345-6789-fedc-ba98-7654321fedcb");
  });

  it("does NOT clobber a known request id when the next response has no header", async () => {
    // First response carries the id.
    global.fetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": "first-known-id",
          },
        }),
    ) as unknown as typeof fetch;
    await api.get("/api/v1/first");
    expect(getLastRequestId()).toBe("first-known-id");

    // Second response has no header (e.g. CDN edge / pre-middleware path).
    global.fetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    ) as unknown as typeof fetch;
    await api.get("/api/v1/second");
    // The first id is still our best support reference.
    expect(getLastRequestId()).toBe("first-known-id");
  });

  it("attaches requestId to thrown ApiError on a 4xx/5xx response", async () => {
    global.fetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "bad request" }), {
          status: 400,
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": "this-failed-here-id",
          },
        }),
    ) as unknown as typeof fetch;

    await expect(api.get("/api/v1/oops")).rejects.toMatchObject({
      status: 400,
      requestId: "this-failed-here-id",
    });
  });

  it("ApiError without an X-Request-ID has requestId = undefined (and we still don't crash)", async () => {
    global.fetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "no header here" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
    ) as unknown as typeof fetch;

    try {
      await api.get("/api/v1/no-header");
      throw new Error("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).requestId).toBeUndefined();
    }
  });
});
