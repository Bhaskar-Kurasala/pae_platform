import { describe, it, expect } from "vitest";
import { activeDaySet, computeStreak } from "@/lib/streak";

function iso(d: Date): string {
  return d.toISOString();
}

function daysAgo(n: number, from: Date = new Date("2026-04-18T12:00:00Z")): Date {
  return new Date(from.getTime() - n * 86400000);
}

describe("computeStreak", () => {
  const now = new Date("2026-04-18T12:00:00Z");

  it("returns 0 when no activity exists", () => {
    expect(computeStreak(new Set(), now)).toBe(0);
  });

  it("returns 0 when last activity is older than one day ago", () => {
    const days = activeDaySet([iso(daysAgo(3, now))]);
    expect(computeStreak(days, now)).toBe(0);
  });

  it("counts today-only as a 1-day streak", () => {
    const days = activeDaySet([iso(now)]);
    expect(computeStreak(days, now)).toBe(1);
  });

  it("counts yesterday-only as a 1-day streak (grace window)", () => {
    const days = activeDaySet([iso(daysAgo(1, now))]);
    expect(computeStreak(days, now)).toBe(1);
  });

  it("counts a run of consecutive days", () => {
    const days = activeDaySet([
      iso(now),
      iso(daysAgo(1, now)),
      iso(daysAgo(2, now)),
      iso(daysAgo(3, now)),
    ]);
    expect(computeStreak(days, now)).toBe(4);
  });

  it("stops at the first gap", () => {
    const days = activeDaySet([
      iso(now),
      iso(daysAgo(1, now)),
      // gap at day 2
      iso(daysAgo(3, now)),
      iso(daysAgo(4, now)),
    ]);
    expect(computeStreak(days, now)).toBe(2);
  });

  it("deduplicates multiple activities on the same day", () => {
    const days = activeDaySet([iso(now), iso(now), iso(now)]);
    expect(computeStreak(days, now)).toBe(1);
  });

  it("ignores null/undefined/invalid timestamps", () => {
    const days = activeDaySet([iso(now), null, undefined, "not a date"]);
    expect(computeStreak(days, now)).toBe(1);
  });
});
