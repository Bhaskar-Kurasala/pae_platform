import { describe, it, expect } from "vitest";

// ── Pure helpers extracted from skill-map components ─────────────────────────

/** Map mastery level to a 0–1 progress value (mirrors ProgressRing in skill-node-card). */
const MASTERY_PROGRESS: Record<string, number> = {
  unknown: 0,
  novice: 0.25,
  learning: 0.5,
  proficient: 0.75,
  mastered: 1,
};

/** Derive a human-readable cluster label from a layer index. */
function layerLabel(layer: number): string {
  if (layer === 0) return "Foundations";
  if (layer === 1) return "Core concepts";
  if (layer === 2) return "Intermediate";
  if (layer === 3) return "Advanced";
  return `Level ${layer + 1}`;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("MASTERY_PROGRESS", () => {
  it("maps unknown to 0", () => {
    expect(MASTERY_PROGRESS["unknown"]).toBe(0);
  });

  it("maps mastered to 1", () => {
    expect(MASTERY_PROGRESS["mastered"]).toBe(1);
  });

  it("maps all five levels to increasing values", () => {
    const levels = ["unknown", "novice", "learning", "proficient", "mastered"];
    const values = levels.map((l) => MASTERY_PROGRESS[l]);
    for (let i = 1; i < values.length; i++) {
      expect(values[i]).toBeGreaterThan(values[i - 1]!);
    }
  });
});

describe("layerLabel", () => {
  it("names layer 0 as Foundations", () => {
    expect(layerLabel(0)).toBe("Foundations");
  });

  it("names layer 1 as Core concepts", () => {
    expect(layerLabel(1)).toBe("Core concepts");
  });

  it("names layer 2 as Intermediate", () => {
    expect(layerLabel(2)).toBe("Intermediate");
  });

  it("names layer 3 as Advanced", () => {
    expect(layerLabel(3)).toBe("Advanced");
  });

  it("generates a Level N label for layers beyond 3", () => {
    expect(layerLabel(4)).toBe("Level 5");
    expect(layerLabel(9)).toBe("Level 10");
  });
});
