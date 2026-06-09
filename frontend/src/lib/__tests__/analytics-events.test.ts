/**
 * PR3/C3.2 — typed analytics event catalog tests.
 *
 * Mocks the underlying `telemetry.capture` + `telemetry.identify`
 * calls and asserts each helper fires the expected event name +
 * property shape. The catalog's whole job is to keep call sites
 * type-safe; these tests pin the wire format so a typo in the helper
 * doesn't quietly mis-name the event in production.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { mockCapture, mockIdentify } = vi.hoisted(() => ({
  mockCapture: vi.fn(),
  mockIdentify: vi.fn(),
}));

vi.mock("@/lib/telemetry", () => ({
  capture: mockCapture,
  identify: mockIdentify,
  reset: vi.fn(),
}));

import * as events from "@/lib/analytics-events";

beforeEach(() => {
  mockCapture.mockReset();
  mockIdentify.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PR3/C3.2 analytics events", () => {
  it("trackSignedUp identifies + captures with method", () => {
    events.trackSignedUp("user-1", "github");
    expect(mockIdentify).toHaveBeenCalledWith("user-1", {
      signup_method: "github",
    });
    expect(mockCapture).toHaveBeenCalledWith("auth.signed_up", {
      method: "github",
    });
  });

  it("trackSignedIn identifies + captures auth.signed_in", () => {
    events.trackSignedIn("user-2");
    expect(mockIdentify).toHaveBeenCalledWith("user-2");
    expect(mockCapture).toHaveBeenCalledWith("auth.signed_in", {});
  });

  it("trackTodayStepDone fires the right per-step event name", () => {
    events.trackTodayStepDone("warmup");
    events.trackTodayStepDone("lesson");
    events.trackTodayStepDone("reflect");
    expect(mockCapture.mock.calls.map((c) => c[0])).toEqual([
      "today.warmup_done",
      "today.lesson_done",
      "today.reflect_done",
    ]);
  });

  it("trackPracticeRun preserves mode + optional exercise_id", () => {
    events.trackPracticeRun({ mode: "capstone" });
    events.trackPracticeRun({ mode: "exercises", exercise_id: "ex-1" });
    expect(mockCapture).toHaveBeenNthCalledWith(1, "practice.run", {
      mode: "capstone",
    });
    expect(mockCapture).toHaveBeenNthCalledWith(2, "practice.run", {
      mode: "exercises",
      exercise_id: "ex-1",
    });
  });

  it("trackNotebookSaved tags by source", () => {
    events.trackNotebookSaved({ source: "practice" });
    expect(mockCapture).toHaveBeenCalledWith("notebook.saved", {
      source: "practice",
    });
  });

  it("trackPromotionConfirmed includes level", () => {
    events.trackPromotionConfirmed({ level: 3 });
    expect(mockCapture).toHaveBeenCalledWith("promotion.confirmed", {
      level: 3,
    });
  });

  it("trackErrorBoundaryCaught includes digest + pathname", () => {
    events.trackErrorBoundaryCaught({
      digest: "abc12345",
      pathname: "/practice",
    });
    expect(mockCapture).toHaveBeenCalledWith("error.boundary_caught", {
      digest: "abc12345",
      pathname: "/practice",
    });
  });

  it("trackErrorApiFailed includes status + path", () => {
    events.trackErrorApiFailed({ status: 500, path: "/api/v1/path/summary" });
    expect(mockCapture).toHaveBeenCalledWith("error.api_failed", {
      status: 500,
      path: "/api/v1/path/summary",
    });
  });
});
