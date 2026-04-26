/**
 * Placement quiz — finalized question copy.
 *
 * COPY OWNERSHIP: this file is final-reviewed marketing copy. Engineers should
 * not edit option labels, headlines, sublines, or paraphrases without ops sign-off
 * — the wording was chosen for psychological effect (Hormozi value-equation framework).
 *
 * Each option carries:
 *   - label: the exact user-facing string (verbatim)
 *   - paraphrase: a grammatically-flowing form used inside echo-card sentences
 *   - systemFix: (Q4 only) the "why this time is different" pillar line that
 *     gets shown when the user picks this option as their failure narrative
 *   - score: a single dimension/value pair the option contributes to scoring
 *
 * The shape is intentionally flat — scoring logic in _quiz-scoring.ts reads
 * `score.dimension` and `score.value` for each chosen option. No nested maps.
 */

export type SkillLevel = "beginner" | "some-basics" | "working-dev" | "mid-level";
export type TrackKey = "analyst" | "scientist" | "ml" | "genai";
export type UrgencyMode = "decided" | "activating";

/** Dimensions a single option can contribute to. Q4 is verbatim-stored (no score). */
export type ScoreDimension =
  | { dimension: "skillLevel"; value: SkillLevel }
  | { dimension: "commitmentIntensity"; value: 1 | 2 | 3 | 4 }
  | { dimension: "track"; value: TrackKey }
  | { dimension: "urgencyMode"; value: UrgencyMode }
  | { dimension: "failureNarrative"; value: string }; // Q4 — the option id, used to look up the systemFix line

export interface QuizOption {
  id: string;
  /** User-facing label — verbatim, do not rewrite. */
  label: string;
  /** Used in echo-card sentence interpolation. Q1/Q3 only; null elsewhere. */
  paraphrase: string | null;
  /** Q4 only: the "Why this time is different" pillar body, after the user's quote. */
  systemFix: string | null;
  score: ScoreDimension;
}

export interface QuizQuestion {
  id: "pain-now" | "pain-future" | "dream" | "not-your-fault" | "speed";
  /** Theme phrase shown after "Question N of 5 ·". */
  theme: string;
  headline: string;
  subline: string | null;
  /** Visual-weight cue: Q2 renders with a slightly heavier card background. */
  visualWeight: "default" | "heavy";
  options: ReadonlyArray<QuizOption>;
}

// ---------------------------------------------------------------------------
// Q1 — Pain Now
// ---------------------------------------------------------------------------

const Q1: QuizQuestion = {
  id: "pain-now",
  theme: "Where you are",
  headline: "Be honest — when you think about your career right now, what's the feeling?",
  subline: "Pick the one that stings most. There's no wrong answer here.",
  visualWeight: "default",
  options: [
    {
      id: "stuck",
      label: "Stuck. I'm watching people I started with pull ahead.",
      paraphrase: "stuck — watching people you started with pull ahead",
      systemFix: null,
      score: { dimension: "skillLevel", value: "beginner" },
    },
    {
      id: "frustrated",
      label: "Frustrated. I keep starting and stopping.",
      paraphrase: "frustrated — caught in the start-stop loop",
      systemFix: null,
      score: { dimension: "skillLevel", value: "some-basics" },
    },
    {
      id: "restless",
      label: "Restless. The work pays — but it's going nowhere.",
      paraphrase: "restless in a role that's going nowhere",
      systemFix: null,
      score: { dimension: "skillLevel", value: "working-dev" },
    },
    {
      id: "behind",
      label: "Behind. AI is moving fast and I'm watching from the sidelines.",
      paraphrase: "behind — watching AI move while you sit on the sidelines",
      systemFix: null,
      score: { dimension: "skillLevel", value: "mid-level" },
    },
  ],
};

// ---------------------------------------------------------------------------
// Q2 — Pain Future (the Hormozi opener — heavy card, no track score)
// ---------------------------------------------------------------------------

const Q2: QuizQuestion = {
  id: "pain-future",
  theme: "Where you'd be",
  headline: "Fast-forward 12 months. Same chair. Same role. Same salary.",
  subline:
    "A friend from your batch just posted a promotion to senior. What's the first thought that hits you?",
  visualWeight: "heavy",
  options: [
    {
      id: "shouldve-started",
      label: "“I should've started when I had the chance.”",
      paraphrase: null,
      systemFix: null,
      score: { dimension: "commitmentIntensity", value: 1 },
    },
    {
      id: "window-closing",
      label: "“I'm watching my window close in real time.”",
      paraphrase: null,
      systemFix: null,
      score: { dimension: "commitmentIntensity", value: 2 },
    },
    {
      id: "left-behind",
      label: "“I'm not behind — I'm being left behind.”",
      paraphrase: null,
      systemFix: null,
      score: { dimension: "commitmentIntensity", value: 3 },
    },
    {
      id: "year-it-stops",
      label: "“This is the year I stop letting this happen.”",
      paraphrase: null,
      systemFix: null,
      score: { dimension: "commitmentIntensity", value: 4 },
    },
  ],
};

// ---------------------------------------------------------------------------
// Q3 — Dream (the deterministic track signal)
// ---------------------------------------------------------------------------

const Q3: QuizQuestion = {
  id: "dream",
  theme: "Where you want to be",
  headline: "What's the version of your life you don't usually say out loud?",
  subline: "The honest one. Not the LinkedIn one.",
  visualWeight: "default",
  options: [
    {
      id: "parents-made-it",
      label: "“Telling my parents I made it — and meaning it.”",
      paraphrase: "to tell your parents you made it — and mean it",
      systemFix: null,
      score: { dimension: "track", value: "analyst" },
    },
    {
      id: "quit-killing-job",
      label: "“Quitting the job that's quietly killing me, on my terms.”",
      paraphrase: "to quit the job that's quietly killing you — on your terms, not theirs",
      systemFix: null,
      score: { dimension: "track", value: "scientist" },
    },
    {
      id: "money-stops",
      label:
        "“Earning enough that money stops being the daily conversation in my head.”",
      paraphrase: "to earn enough that money stops being the daily conversation in your head",
      systemFix: null,
      score: { dimension: "track", value: "ml" },
    },
    {
      id: "name-on-it",
      label: "“Building something with my name on it. Working for me, not a manager.”",
      paraphrase:
        "to build something with your name on it — working for yourself, not a manager",
      systemFix: null,
      score: { dimension: "track", value: "genai" },
    },
  ],
};

// ---------------------------------------------------------------------------
// Q4 — Not Your Fault (externalize blame; verbatim quote drives the result-screen pillar)
// ---------------------------------------------------------------------------

const Q4: QuizQuestion = {
  id: "not-your-fault",
  theme: "Why it hasn't worked yet",
  headline: "Why hasn't it happened yet?",
  subline: "It's probably not what you've been telling yourself.",
  visualWeight: "default",
  options: [
    {
      id: "no-40-hours",
      label:
        "“Every roadmap was built for people with 40 free hours a week. That's not my life.”",
      paraphrase: null,
      systemFix:
        "every lesson is sized for 60 minutes after dinner — not a free Saturday. The track is built for 7 hours a week, max.",
      score: { dimension: "failureNarrative", value: "no-40-hours" },
    },
    {
      id: "syntax-not-shipping",
      label:
        "“Tutorials taught me syntax. Nobody taught me how to ship something real.”",
      paraphrase: null,
      systemFix: "every module ends with a shipped artifact — not a quiz score.",
      score: { dimension: "failureNarrative", value: "syntax-not-shipping" },
    },
    {
      id: "too-many-options",
      label: "“Too many options, zero clarity on which one actually works.”",
      paraphrase: null,
      systemFix:
        "one roadmap. One sequence. The choice you didn't have time to research — already made.",
      score: { dimension: "failureNarrative", value: "too-many-options" },
    },
    {
      id: "free-youtube",
      label:
        "“I kept betting on free YouTube paths that were never going to get me there.”",
      paraphrase: null,
      systemFix:
        "the path no free YouTube playlist could give you — assembled, sequenced, and with a mentor checking your work at 11pm Tuesday.",
      score: { dimension: "failureNarrative", value: "free-youtube" },
    },
  ],
};

// ---------------------------------------------------------------------------
// Q5 — Speed with Consequence (urgency mode — tunes the CTA)
// ---------------------------------------------------------------------------

const Q5: QuizQuestion = {
  id: "speed",
  theme: "When this changes",
  headline: "When does this stop being something you're “thinking about”?",
  subline: null,
  visualWeight: "default",
  options: [
    {
      id: "today",
      label: "“Today. I'm tired of being the person who keeps thinking about it.”",
      paraphrase: "Today. You're done thinking about it.",
      systemFix: null,
      score: { dimension: "urgencyMode", value: "activating" },
    },
    {
      id: "this-month",
      label: "“This month. I'm not letting another quarter slip.”",
      paraphrase: "This month. No more slipped quarters.",
      systemFix: null,
      score: { dimension: "urgencyMode", value: "activating" },
    },
    {
      id: "right-path",
      label:
        "“I'm ready when the right path is in front of me — and I think it just was.”",
      paraphrase: "You were waiting for the right path. You're looking at it.",
      systemFix: null,
      score: { dimension: "urgencyMode", value: "decided" },
    },
    {
      id: "decided",
      label: "“I've decided. I'm just here to find out which track.”",
      paraphrase: "You've decided. The only question left was which track.",
      systemFix: null,
      score: { dimension: "urgencyMode", value: "decided" },
    },
  ],
};

// ---------------------------------------------------------------------------
// Public export — ordered list, used by the state machine for sequencing.
// ---------------------------------------------------------------------------

export const QUESTIONS: ReadonlyArray<QuizQuestion> = [Q1, Q2, Q3, Q4, Q5] as const;

/** Total number of questions — single source of truth for progress %, header labels, etc. */
export const TOTAL_QUESTIONS = QUESTIONS.length;

/** The user's selected option id per question id. Partial during the flow, complete at result. */
export type AnswersMap = Partial<Record<QuizQuestion["id"], string>>;
