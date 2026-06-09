/**
 * PR3/C4.1 — Frontend Sentry config no-op-safety tests.
 *
 * Three guarantees:
 *   1. With NEXT_PUBLIC_SENTRY_DSN unset, the client config import is
 *      a no-op — Sentry.init is NOT called.
 *   2. With the DSN set, init IS called with the expected sampling
 *      rates (0% in dev, 5% in prod).
 *   3. The instrumentation files don't crash on import in either
 *      runtime.
 *
 * We can't fully exercise the SDK in jsdom (it expects browser APIs
 * Sentry shims with feature detection), so we mock @sentry/nextjs at
 * the module boundary and assert against the mocked init call.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { mockInit } = vi.hoisted(() => ({
  mockInit: vi.fn(),
}));

vi.mock("@sentry/nextjs", () => ({
  init: mockInit,
}));

const originalEnv = { ...process.env };

beforeEach(() => {
  vi.resetModules();
  mockInit.mockReset();
});

afterEach(() => {
  process.env = { ...originalEnv };
  vi.restoreAllMocks();
});

describe("PR3/C4.1 Sentry client config", () => {
  it("does NOT call Sentry.init when DSN is unset", async () => {
    delete process.env.NEXT_PUBLIC_SENTRY_DSN;
    await import("../../sentry.client.config");
    expect(mockInit).not.toHaveBeenCalled();
  });

  it("calls Sentry.init when DSN is set, with 0% trace sampling in dev", async () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = "https://fake@sentry.io/1";
    process.env.NEXT_PUBLIC_SENTRY_ENV = "development";
    await import("../../sentry.client.config");
    expect(mockInit).toHaveBeenCalledTimes(1);
    const call = mockInit.mock.calls[0][0];
    expect(call.dsn).toBe("https://fake@sentry.io/1");
    expect(call.environment).toBe("development");
    expect(call.tracesSampleRate).toBe(0);
    expect(call.sendDefaultPii).toBe(false);
  });

  it("uses 5% trace sampling in production", async () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = "https://fake@sentry.io/1";
    process.env.NEXT_PUBLIC_SENTRY_ENV = "production";
    await import("../../sentry.client.config");
    const call = mockInit.mock.calls[0][0];
    expect(call.tracesSampleRate).toBe(0.05);
  });

  it("server config no-ops without DSN", async () => {
    delete process.env.NEXT_PUBLIC_SENTRY_DSN;
    await import("../../sentry.server.config");
    expect(mockInit).not.toHaveBeenCalled();
  });

  it("edge config no-ops without DSN", async () => {
    delete process.env.NEXT_PUBLIC_SENTRY_DSN;
    await import("../../sentry.edge.config");
    expect(mockInit).not.toHaveBeenCalled();
  });
});
