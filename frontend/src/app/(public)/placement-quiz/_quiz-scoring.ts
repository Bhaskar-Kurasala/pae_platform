/**
 * Placement quiz — scoring (pure functions, fully testable in isolation).
 *
 * Inputs: AnswersMap (the user's option-id selections per question id).
 * Outputs: recommended track, confidence percent, urgency mode, commitment
 *          intensity, failure narrative, and the paraphrase strings used by
 *          the result-screen echo card.
 *
 * Confidence is honestly clamped to 88–96 inclusive — see getConfidencePercent.
 * The clamp is deliberate: a quiz that recommends a track shouldn't display
 * "you're a 12% match" for that track; that contradicts the recommendation.
 * Within the clamp, the score is *deterministic* (same answers = same %),
 * so the same user always sees the same number.
 */

import {
  QUESTIONS,
  type AnswersMap,
  type QuizQuestion,
  type SkillLevel,
  type TrackKey,
  type UrgencyMode,
} from "./_quiz-questions";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function findQuestion(id: QuizQuestion["id"]): QuizQuestion {
  const q = QUESTIONS.find((qq) => qq.id === id);
  if (!q) throw new Error(`Quiz question not found: ${id}`);
  return q;
}

function findOption(questionId: QuizQuestion["id"], optionId: string | undefined) {
  if (!optionId) return null;
  const q = findQuestion(questionId);
  return q.options.find((o) => o.id === optionId) ?? null;
}

// ---------------------------------------------------------------------------
// Per-track ideal profile — used for confidence scoring.
// "Ideal" = which skill level + which Q4 narrative + which urgency mode this
// track maps best to. Hits add to the alignment score; misses don't penalise
// (the track is still the user's pick — confidence just narrows).
// ---------------------------------------------------------------------------

interface TrackIdealProfile {
  /** Skill levels that align with this track. */
  skillLevels: ReadonlyArray<SkillLevel>;
  /** Q4 failure narratives that this track's system fixes are built for. */
  failureNarratives: ReadonlyArray<string>;
  /** Urgency modes that match this track's typical buyer. */
  urgencyModes: ReadonlyArray<UrgencyMode>;
  /** A small per-track integer offset (0–4) to keep confidence% deterministic
   *  but visually varied — same answer set on different tracks shows different %. */
  confidenceOffset: number;
}

const TRACK_PROFILES: Record<TrackKey, TrackIdealProfile> = {
  analyst: {
    skillLevels: ["beginner", "some-basics"],
    failureNarratives: ["no-40-hours", "syntax-not-shipping"],
    urgencyModes: ["activating", "decided"],
    confidenceOffset: 1,
  },
  scientist: {
    skillLevels: ["some-basics", "working-dev"],
    failureNarratives: ["too-many-options", "syntax-not-shipping"],
    urgencyModes: ["activating", "decided"],
    confidenceOffset: 3,
  },
  ml: {
    skillLevels: ["working-dev", "mid-level"],
    failureNarratives: ["syntax-not-shipping", "free-youtube"],
    urgencyModes: ["decided", "activating"],
    confidenceOffset: 2,
  },
  genai: {
    skillLevels: ["working-dev", "mid-level"],
    failureNarratives: ["free-youtube", "too-many-options"],
    urgencyModes: ["decided", "activating"],
    confidenceOffset: 4,
  },
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Q3 deterministically picks the track. No tiebreaker logic needed because
 * Q3 always returns one of the four track keys (single-select, required).
 * Returns null if Q3 hasn't been answered yet.
 */
export function getRecommendedTrack(answers: AnswersMap): TrackKey | null {
  const opt = findOption("dream", answers["dream"]);
  if (!opt) return null;
  if (opt.score.dimension !== "track") return null;
  return opt.score.value;
}

/**
 * Q5 picks urgency. Default to 'activating' if not answered (treat undecided
 * users as needing the action-trigger CTA — the safer default).
 */
export function getUrgencyMode(answers: AnswersMap): UrgencyMode {
  const opt = findOption("speed", answers["speed"]);
  if (!opt || opt.score.dimension !== "urgencyMode") return "activating";
  return opt.score.value;
}

/**
 * Q2 commitment intensity 1–4. Default to 2 (mid-soft) if not answered.
 * Used to tune urgency tone on the result-screen guarantee/timestamp blocks.
 */
export function getCommitmentIntensity(answers: AnswersMap): 1 | 2 | 3 | 4 {
  const opt = findOption("pain-future", answers["pain-future"]);
  if (!opt || opt.score.dimension !== "commitmentIntensity") return 2;
  return opt.score.value;
}

/**
 * Q1 skill level. Defaults to 'some-basics' (most populous slice) if missing.
 */
export function getSkillLevel(answers: AnswersMap): SkillLevel {
  const opt = findOption("pain-now", answers["pain-now"]);
  if (!opt || opt.score.dimension !== "skillLevel") return "some-basics";
  return opt.score.value;
}

/**
 * Q4 failure narrative — the option id (used to look up the systemFix line).
 * Returns null if Q4 hasn't been answered.
 */
export function getFailureNarrative(answers: AnswersMap): string | null {
  const opt = findOption("not-your-fault", answers["not-your-fault"]);
  if (!opt) return null;
  return opt.id;
}

/**
 * Confidence percent — 88..96 inclusive, deterministic per answer set.
 *
 * Algorithm:
 *   raw = (skillLevel match: 0|1) + (failureNarrative match: 0|1) + (urgency match: 0|1)
 *         + 1 (Q3 always matches — it IS the track) + (commitmentIntensity normalized: 0|1)
 *   raw is in 1..5. Normalize:
 *     clamped = 88 + (raw - 1) * 2  → 88, 90, 92, 94, 96
 *   add the per-track offset (0..4), modulo 4, to break ties between tracks.
 *
 * Worst case (only Q3 answered) = 88. Best case (all 5 align) = 96.
 */
export function getConfidencePercent(answers: AnswersMap): number {
  const track = getRecommendedTrack(answers);
  if (!track) return 88;
  const profile = TRACK_PROFILES[track];

  let raw = 1; // Q3 — the track itself; always counts.

  const skill = getSkillLevel(answers);
  if (profile.skillLevels.includes(skill)) raw += 1;

  const failureId = getFailureNarrative(answers);
  if (failureId && profile.failureNarratives.includes(failureId)) raw += 1;

  const urgency = getUrgencyMode(answers);
  if (profile.urgencyModes.includes(urgency)) raw += 1;

  // Commitment intensity contributes 0|1 — high-commitment (3–4) always counts,
  // low-commitment (1–2) only counts when track is analyst (entry track,
  // softer commitment is normal there).
  const intensity = getCommitmentIntensity(answers);
  if (intensity >= 3 || track === "analyst") raw += 1;

  // Map raw 1..5 → 88, 90, 92, 94, 96 (step 2). Then add a small per-track
  // jitter (0..1) so two tracks with identical raw scores don't print the
  // same % — keeps the result feeling computed, not assigned.
  const base = 88 + (raw - 1) * 2;
  const jitter = profile.confidenceOffset % 2; // 0 or 1
  const result = Math.min(96, Math.max(88, base + jitter));
  return result;
}

// ---------------------------------------------------------------------------
// Echo-card paraphrase lookup — the result screen reads these directly.
// Returning empty strings on missing answers lets the result render gracefully
// even if state is somehow incomplete (shouldn't happen, but defensive).
// ---------------------------------------------------------------------------

export function getEchoPieces(answers: AnswersMap): {
  q1Paraphrase: string;
  q2Verbatim: string;
  q3Paraphrase: string;
  q4Verbatim: string;
  q5Paraphrase: string;
  q4SystemFix: string;
} {
  const q1 = findOption("pain-now", answers["pain-now"]);
  const q2 = findOption("pain-future", answers["pain-future"]);
  const q3 = findOption("dream", answers["dream"]);
  const q4 = findOption("not-your-fault", answers["not-your-fault"]);
  const q5 = findOption("speed", answers["speed"]);

  return {
    q1Paraphrase: q1?.paraphrase ?? "",
    q2Verbatim: q2?.label ?? "",
    q3Paraphrase: q3?.paraphrase ?? "",
    q4Verbatim: q4?.label ?? "",
    q5Paraphrase: q5?.paraphrase ?? "",
    q4SystemFix: q4?.systemFix ?? "",
  };
}

/** True when every question has a recorded answer. */
export function isComplete(answers: AnswersMap): boolean {
  return QUESTIONS.every((q) => Boolean(answers[q.id]));
}
