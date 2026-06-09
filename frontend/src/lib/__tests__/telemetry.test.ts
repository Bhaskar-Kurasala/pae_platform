/**
 * PR3/C3.1 — frontend telemetry shim tests.
 *
 * The `posthog-js` SDK is browser-only and lazy-imported. We test the
 * three guarantees that every call site relies on:
 *
 *   1. With NEXT_PUBLIC_POSTHOG_KEY unset, capture/identify/reset are
 *      total no-ops and never throw — the env-less dev / CI path.
 *   2. capture() is fire-and-forget — it returns synchronously even
 *      though it kicks off an async init.
 *   3. The shim doesn't crash on import in an SSR context (no
 *      `window`).
 *
 * We don't try to test the actual posthog-js wiring here — that would
 * require a full DOM stub and a moving SDK target. That's a Playwright
 * smoke concern.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Snapshot + restore process.env between tests so toggling the key
// doesn't leak into adjacent suites.
const originalEnv = { ...process.env };

beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  process.env = { ...originalEnv };
  vi.restoreAllMocks();
});

describe("PR3/C3.1 telemetry shim", () => {
  it("capture() is a no-op (and doesn't throw) when key is missing", async () => {
    delete process.env.NEXT_PUBLIC_POSTHOG_KEY;
    const tel = await import("@/lib/telemetry");
    expect(() => tel.capture("today.summary_loaded")).not.toThrow();
    expect(() =>
      tel.capture("practice.run", { exerciseId: "ex-1" }),
    ).not.toThrow();
  });

  it("identify() is a no-op when key is missing", async () => {
    delete process.env.NEXT_PUBLIC_POSTHOG_KEY;
    const tel = await import("@/lib/telemetry");
    expect(() => tel.identify("user-1")).not.toThrow();
    expect(() =>
      tel.identify("user-2", { plan: "free" }),
    ).not.toThrow();
  });

  it("reset() is a no-op when client never initialized", async () => {
    delete process.env.NEXT_PUBLIC_POSTHOG_KEY;
    const tel = await import("@/lib/telemetry");
    expect(() => tel.reset()).not.toThrow();
  });

  it("capture() returns synchronously even when configured", async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = "phc_fake";
    const tel = await import("@/lib/telemetry");
    // The function must not return a Promise — call sites are inside
    // sync onClick handlers and onSuccess callbacks that shouldn't
    // await us.
    const result = tel.capture("today.warmup_done");
    expect(result).toBeUndefined();
  });
});
