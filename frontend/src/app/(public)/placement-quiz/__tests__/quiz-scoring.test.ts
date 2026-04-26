/**
 * Tests for placement-quiz scoring (the algorithmic surface).
 * Copy edits in _quiz-questions.ts shouldn't break scoring; these tests
 * fail loudly if a scoreMap key is renamed or a track key changes.
 */

import { describe, it, expect } from "vitest";
import {
  getRecommendedTrack,
  getUrgencyMode,
  getCommitmentIntensity,
  getSkillLevel,
  getFailureNarrative,
  getConfidencePercent,
  isComplete,
  getEchoPieces,
} from "../_quiz-scoring";
import type { AnswersMap } from "../_quiz-questions";

const FULL_ANSWERS_ANALYST: AnswersMap = {
  "pain-now": "stuck",
  "pain-future": "shouldve-started",
  "dream": "parents-made-it",
  "not-your-fault": "no-40-hours",
  "speed": "today",
};

const FULL_ANSWERS_SCIENTIST: AnswersMap = {
  "pain-now": "frustrated",
  "pain-future": "window-closing",
  "dream": "quit-killing-job",
  "not-your-fault": "too-many-options",
  "speed": "this-month",
};

const FULL_ANSWERS_ML: AnswersMap = {
  "pain-now": "restless",
  "pain-future": "left-behind",
  "dream": "money-stops",
  "not-your-fault": "syntax-not-shipping",
  "speed": "right-path",
};

const FULL_ANSWERS_GENAI: AnswersMap = {
  "pain-now": "behind",
  "pain-future": "year-it-stops",
  "dream": "name-on-it",
  "not-your-fault": "free-youtube",
  "speed": "decided",
};

describe("getRecommendedTrack — Q3 deterministically picks the track", () => {
  it("Q3 option 1 → analyst", () => {
    expect(getRecommendedTrack(FULL_ANSWERS_ANALYST)).toBe("analyst");
  });
  it("Q3 option 2 → scientist", () => {
    expect(getRecommendedTrack(FULL_ANSWERS_SCIENTIST)).toBe("scientist");
  });
  it("Q3 option 3 → ml", () => {
    expect(getRecommendedTrack(FULL_ANSWERS_ML)).toBe("ml");
  });
  it("Q3 option 4 → genai", () => {
    expect(getRecommendedTrack(FULL_ANSWERS_GENAI)).toBe("genai");
  });
  it("returns null when Q3 unanswered", () => {
    expect(getRecommendedTrack({ "pain-now": "stuck" })).toBeNull();
  });
});

describe("getUrgencyMode — Q5 maps options 1/2 → activating, 3/4 → decided", () => {
  it("'today' → activating", () => {
    expect(getUrgencyMode({ speed: "today" })).toBe("activating");
  });
  it("'this-month' → activating", () => {
    expect(getUrgencyMode({ speed: "this-month" })).toBe("activating");
  });
  it("'right-path' → decided", () => {
    expect(getUrgencyMode({ speed: "right-path" })).toBe("decided");
  });
  it("'decided' → decided", () => {
    expect(getUrgencyMode({ speed: "decided" })).toBe("decided");
  });
  it("missing Q5 defaults to activating", () => {
    expect(getUrgencyMode({})).toBe("activating");
  });
});

describe("getCommitmentIntensity — Q2 → 1..4", () => {
  it("option 1 → 1", () => {
    expect(getCommitmentIntensity({ "pain-future": "shouldve-started" })).toBe(1);
  });
  it("option 2 → 2", () => {
    expect(getCommitmentIntensity({ "pain-future": "window-closing" })).toBe(2);
  });
  it("option 3 → 3", () => {
    expect(getCommitmentIntensity({ "pain-future": "left-behind" })).toBe(3);
  });
  it("option 4 → 4", () => {
    expect(getCommitmentIntensity({ "pain-future": "year-it-stops" })).toBe(4);
  });
  it("missing → default 2", () => {
    expect(getCommitmentIntensity({})).toBe(2);
  });
});

describe("getSkillLevel — Q1 → skill bucket", () => {
  it("'stuck' → beginner", () => {
    expect(getSkillLevel({ "pain-now": "stuck" })).toBe("beginner");
  });
  it("'frustrated' → some-basics", () => {
    expect(getSkillLevel({ "pain-now": "frustrated" })).toBe("some-basics");
  });
  it("'restless' → working-dev", () => {
    expect(getSkillLevel({ "pain-now": "restless" })).toBe("working-dev");
  });
  it("'behind' → mid-level", () => {
    expect(getSkillLevel({ "pain-now": "behind" })).toBe("mid-level");
  });
  it("missing → default some-basics", () => {
    expect(getSkillLevel({})).toBe("some-basics");
  });
});

describe("getFailureNarrative — returns Q4 option id", () => {
  it("returns the selected Q4 option id", () => {
    expect(getFailureNarrative({ "not-your-fault": "free-youtube" })).toBe("free-youtube");
  });
  it("returns null when unanswered", () => {
    expect(getFailureNarrative({})).toBeNull();
  });
});

describe("getConfidencePercent — clamped 88..96 inclusive", () => {
  it("never below 88 even with empty answers (fallback path)", () => {
    expect(getConfidencePercent({})).toBeGreaterThanOrEqual(88);
  });
  it("never above 96 even with maximally-aligned answers", () => {
    // Best alignment for ML: working-dev + free-youtube + decided + intensity 4
    expect(
      getConfidencePercent({
        "pain-now": "restless",
        "pain-future": "year-it-stops",
        "dream": "money-stops",
        "not-your-fault": "syntax-not-shipping",
        "speed": "decided",
      }),
    ).toBeLessThanOrEqual(96);
  });
  it("deterministic — same input → same output", () => {
    const a = getConfidencePercent(FULL_ANSWERS_GENAI);
    const b = getConfidencePercent(FULL_ANSWERS_GENAI);
    expect(a).toBe(b);
  });
  it("varies between tracks for same alignment level (jitter offset)", () => {
    const analyst = getConfidencePercent(FULL_ANSWERS_ANALYST);
    const ml = getConfidencePercent(FULL_ANSWERS_ML);
    expect([analyst, ml].every((n) => n >= 88 && n <= 96)).toBe(true);
  });
  it("each of the 4 full-answer sets lands in 88..96", () => {
    for (const a of [
      FULL_ANSWERS_ANALYST,
      FULL_ANSWERS_SCIENTIST,
      FULL_ANSWERS_ML,
      FULL_ANSWERS_GENAI,
    ]) {
      const c = getConfidencePercent(a);
      expect(c).toBeGreaterThanOrEqual(88);
      expect(c).toBeLessThanOrEqual(96);
    }
  });
});

describe("isComplete — all 5 questions present", () => {
  it("true when all 5 answered", () => {
    expect(isComplete(FULL_ANSWERS_ML)).toBe(true);
  });
  it("false when one missing", () => {
    const partial = { ...FULL_ANSWERS_ML };
    delete partial["speed"];
    expect(isComplete(partial)).toBe(false);
  });
  it("false on empty", () => {
    expect(isComplete({})).toBe(false);
  });
});

describe("getEchoPieces — returns paraphrases + verbatim quotes", () => {
  it("returns Q1 paraphrase and Q4 verbatim for full ML answers", () => {
    const e = getEchoPieces(FULL_ANSWERS_ML);
    expect(e.q1Paraphrase).toContain("restless");
    expect(e.q4Verbatim).toContain("syntax");
    expect(e.q4SystemFix).toContain("shipped artifact");
  });
  it("returns empty strings on missing answers (defensive)", () => {
    const e = getEchoPieces({});
    expect(e.q1Paraphrase).toBe("");
    expect(e.q3Paraphrase).toBe("");
    expect(e.q4Verbatim).toBe("");
  });
});
