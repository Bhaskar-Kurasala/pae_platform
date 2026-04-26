/**
 * Placement quiz — configuration (track marketing meta, copy, verified flags).
 *
 * EDIT-WITHOUT-CODE-CHANGES: ops can tune track stats, value-stack numbers,
 * included items, and per-day comparisons here without touching components.
 *
 * VERIFIED FLAG: every stat that isn't grounded in real outcome data carries
 * `verified: false`. The UI renders a [PLACEHOLDER] badge in dev/staging
 * (NODE_ENV !== "production") so unverified stats can't accidentally ship.
 * Flip to `verified: true` after ops confirms with real data.
 *
 * COHORT: there is no cohort_starts_at in the courses DB. Block H is omitted
 * entirely until that field exists. Adding cohort data later = set
 * COHORT.enabled = true and provide startsAt + seatsLeft.
 */

import type { TrackKey } from "./_quiz-questions";

// ---------------------------------------------------------------------------
// Stat type — every numeric/textual claim that isn't a price runs through this.
// The component layer reads `verified` to decide whether to render the badge.
// ---------------------------------------------------------------------------

export interface VerifiedStat<T = string> {
  value: T;
  verified: boolean;
  /** Internal note for the verification checklist in docs/placement-quiz.md. */
  note?: string;
}

// ---------------------------------------------------------------------------
// Track meta — one entry per Q3 track signal.
// ---------------------------------------------------------------------------

export interface TrackMeta {
  /** Maps the quiz-internal track key to the courses-table slug for live pricing. */
  courseSlug:
    | "data-analyst"
    | "data-scientist"
    | "ml-engineer"
    | "genai-engineer";
  /** Display name on the result screen and CTA. */
  displayName: string;
  /** One-line tagline shown under the verdict headline. */
  tagline: string;

  /** Pillar 1 — "Your Dream" stats. */
  cohortSize: VerifiedStat<number>;
  successRate: VerifiedStat<number>; // percent, e.g. 71
  averageOutcome: VerifiedStat<string>; // free-form: "$78k median post-placement", etc.

  /** Result-screen "Day 1 / Day X / Day Y" timeline (Pillar 3). */
  timeline: {
    shipDay: number; // when the first project ships
    resumeDay: number; // when it's recruiter-visible on resume
  };

  /** Pillar 4 — effort relief beat. Per-track because hours range varies. */
  effortLine: string;

  /** What's-included stack (Block D). 6–8 concrete deliverables. */
  included: ReadonlyArray<string>;

  /** Anchor pricing comparison (Block E). Lines summed for comparable-value total. */
  anchor: ReadonlyArray<{ label: string; price: number }>;

  /** Per-day comparison tail line under the price (Block E). */
  perDayLine: string;

  /** Q3 dream paraphrase reused inside the guarantee block (Block F). */
  dreamForGuarantee: string;
}

// ---------------------------------------------------------------------------
// TRACKS — the four Q3 destinations.
//
// All cohortSize/successRate/averageOutcome stats are CURRENTLY UNVERIFIED.
// Numbers reuse the catalog salary tooltips (also unverified — see docs).
// Replace with real outcome data before any paid traffic hits this funnel.
// ---------------------------------------------------------------------------

export const TRACKS: Record<TrackKey, TrackMeta> = {
  analyst: {
    courseSlug: "data-analyst",
    displayName: "Data Analyst",
    tagline: "The shortest honest path from where you are to a tech paycheque.",
    cohortSize: {
      value: 312,
      verified: false,
      note: "Placeholder. Replace with actual student count for this track.",
    },
    successRate: {
      value: 71,
      verified: false,
      note: "Placeholder. Replace with verified placement rate within 6 months.",
    },
    averageOutcome: {
      value: "$78k median entry salary, US",
      verified: false,
      note: "From catalog tooltip — also unverified. Verify both surfaces together.",
    },
    timeline: { shipDay: 18, resumeDay: 45 },
    effortLine:
      "5–10 hours a week. Built assuming you have a job, a family, a commute, and a life. Burnout isn't a feature.",
    included: [
      "8 lessons · SQL, pandas at scale, viz, stakeholder comms",
      "22 labs on real retail + marketing datasets",
      "Dashboard capstone graded by a working analyst",
      "1-on-1 mentor reviews on every project",
      "2 mock interviews + resume + LinkedIn rebuild with a hiring manager",
      "Job-board referrals to hiring partners",
      "Lifetime access to lessons + future updates",
      "Direct DM access to instructors",
    ],
    anchor: [
      { label: "Standalone analytics bootcamp", price: 2500 },
      { label: "1-on-1 mentor (3 months)", price: 600 },
      { label: "Resume + interview coaching", price: 350 },
    ],
    perDayLine: "Less than two coffees a week — for the next 6 months.",
    dreamForGuarantee:
      "telling your parents you made it — and meaning it",
  },

  scientist: {
    courseSlug: "data-scientist",
    displayName: "Data Scientist",
    tagline: "The career-switch path for people who refuse to stay in the wrong room.",
    cohortSize: {
      value: 186,
      verified: false,
      note: "Placeholder. Replace with actual student count for this track.",
    },
    successRate: {
      value: 64,
      verified: false,
      note: "Placeholder. Replace with verified switch-success rate within 9 months.",
    },
    averageOutcome: {
      value: "$112k median post-switch salary, US",
      verified: false,
      note: "From catalog tooltip — also unverified. Verify both surfaces together.",
    },
    timeline: { shipDay: 21, resumeDay: 60 },
    effortLine:
      "8–12 hours a week. We assume you're switching while still working. The path is built for that exact constraint.",
    included: [
      "10 lessons · stats, experimentation, ML foundations, deployment",
      "28 labs · A/B tests, feature engineering, model ops",
      "Kaggle-grade capstone with peer + mentor review",
      "1-on-1 mentor reviews from a senior data scientist",
      "2 mock technical interviews + resume + LinkedIn rebuild",
      "Hiring-partner referrals + salary negotiation playbook",
      "Lifetime access + private student community",
      "Direct DM access to instructors",
    ],
    anchor: [
      { label: "Standalone DS bootcamp", price: 4000 },
      { label: "Senior DS mentor sessions", price: 900 },
      { label: "Interview prep package", price: 500 },
    ],
    perDayLine: "Less than one Netflix family plan a month — for the path that actually changes the job.",
    dreamForGuarantee:
      "quitting the job that's quietly killing you — on your terms, not theirs",
  },

  ml: {
    courseSlug: "ml-engineer",
    displayName: "ML Engineer",
    tagline: "Production ML — the salary leap path. No notebooks-only theatre.",
    cohortSize: {
      value: 142,
      verified: false,
      note: "Placeholder. Replace with actual student count for this track.",
    },
    successRate: {
      value: 68,
      verified: false,
      note: "Placeholder. Replace with verified salary-bump rate within 12 months.",
    },
    averageOutcome: {
      value: "$145k median post-placement salary, US",
      verified: false,
      note: "From catalog tooltip — also unverified. Verify both surfaces together.",
    },
    timeline: { shipDay: 24, resumeDay: 75 },
    effortLine:
      "10–14 hours a week. The path is sized for working engineers — every weeknight earns you a piece of the next role.",
    included: [
      "12 lessons · pipelines, feature stores, serving, monitoring",
      "34 labs · Docker, GPUs, batch + online inference",
      "End-to-end production ML system as capstone",
      "1-on-1 mentor reviews from a senior MLE on every milestone",
      "FAANG-style system-design mock interviews until you pass one",
      "Hiring-partner referrals + salary negotiation playbook",
      "Lifetime access + private student community",
      "Direct DM access to instructors",
    ],
    anchor: [
      { label: "Standalone MLE bootcamp", price: 6500 },
      { label: "Senior MLE mentor hours", price: 1500 },
      { label: "System-design coaching", price: 800 },
    ],
    perDayLine: "Less than what a senior MLE makes in 90 minutes — once.",
    dreamForGuarantee:
      "earning enough that money stops being the daily conversation in your head",
  },

  genai: {
    courseSlug: "genai-engineer",
    displayName: "GenAI Engineer",
    tagline: "The track for the people who want to build the thing — not maintain it.",
    cohortSize: {
      value: 94,
      verified: false,
      note: "Placeholder. Replace with actual student count for this track.",
    },
    successRate: {
      value: 73,
      verified: false,
      note: "Placeholder. Replace with verified launch-or-place rate within 12 months.",
    },
    averageOutcome: {
      value: "$180k+ post-placement, or first $10k of freelance income within 90 days",
      verified: false,
      note: "From catalog tooltip — also unverified. Verify both surfaces together.",
    },
    timeline: { shipDay: 27, resumeDay: 90 },
    effortLine:
      "10–20 hours a week. The path is sized for serious mode — but pace is yours, not a cohort's.",
    included: [
      "14 lessons · RAG, agents, evals, LLMOps, safety",
      "38 labs · tool use, long-context, reasoning chains",
      "Agentic capstone reviewed 1-on-1 by a mentor from a GenAI company",
      "Direct intros to hiring partners actively seeking GenAI engineers",
      "FAANG + frontier-lab mock interviews until you pass one",
      "Salary + freelance pricing negotiation playbook",
      "Lifetime access + alumni-only GenAI community",
      "Direct DM access to instructors",
    ],
    anchor: [
      { label: "Standalone GenAI bootcamp", price: 8000 },
      { label: "GenAI-company mentor hours", price: 2000 },
      { label: "Interview + negotiation coaching", price: 1000 },
    ],
    perDayLine: "Less than what one client retainer pays in a single week.",
    dreamForGuarantee:
      "building something with your name on it — working for yourself, not a manager",
  },
} as const;

// ---------------------------------------------------------------------------
// Result-screen prose templates. Edit here, not in components.
// ---------------------------------------------------------------------------

export const COPY = {
  intro: {
    headline: "Let's find your fastest path.",
    subline:
      "5 questions. 4 minutes. One personalized track — and the honest reason it'll work this time.",
    cta: "Begin",
    footer: "No email required to see your result.",
  },
  loading: {
    line: "Matching you to the right track…",
    /** Hold time in ms. Reduced-motion users get a much shorter hold (handled in component). */
    holdMs: 2000,
    holdMsReducedMotion: 400,
  },
  result: {
    verdictPrefix: "Your fit:",
    confidenceLabel: "match",
    echoHeader: "Here's what you just told us:",
    echoFinalLine: "This track was built for exactly that person.",
    pillarsHeader: "Why this track. Specifically for you.",
    pillarTitles: {
      dream: "Your Dream",
      different: "Why this time is different",
      speed: "Speed",
      effort: "Effort",
    },
    speedTemplate: (shipDay: number, resumeDay: number) =>
      `Day 1 you start a real project. Day ${shipDay} you ship it. Day ${resumeDay} it's on your resume — public, recruiter-visible. Not "lesson 1." Shipped.`,
    includedHeader: "What you get:",
    priceCard: {
      anchorHeader: "Standalone, this would cost:",
      yourPriceLabel: "Your price:",
      oneTime: "one-time",
      comparableValueLabel: "Comparable value:",
    },
    guarantee: {
      header: "The “We Believe You'll Outperform This” Guarantee",
      body: (dreamPhrase: string) =>
        `Take 14 days. Complete the first module. If you don't agree this is the most well-built path you've ever seen toward ${dreamPhrase} — full refund, and we'll personally send you 2 better resources to try next.`,
      bodyClose: "No “are you sure” email. No friction.",
      emphasis: "We win when you win — not when you stay stuck paying us.",
    },
    cta: {
      decided: (track: string) => `Enroll in ${track}`,
      activating: (track: string) => `Start ${track} today`,
      secondary: "See full curriculum first",
    },
    timestamp: {
      withTime: (startTime: string, endTime: string) =>
        `You started this quiz at ${startTime}. You have your answer at ${endTime}.`,
      clamped:
        "You took the quiz. You have your answer.",
      closingLine:
        "The version of you that took 4 minutes today is the one your future self is going to thank.",
    },
  },
} as const;

// ---------------------------------------------------------------------------
// Cohort block (Block H) — currently disabled. Set enabled = true and provide
// startsAt + seatsLeft when the backend exposes a real cohort schema.
// ---------------------------------------------------------------------------

export const COHORT = {
  enabled: false,
  startsAt: null as string | null, // e.g. "2026-05-12"
  seatsLeft: null as number | null, // e.g. 14
} as const;

// ---------------------------------------------------------------------------
// Echo card sentence template — produces the body line of Block B.
// Pulled out here so a copy edit doesn't require touching the component.
// ---------------------------------------------------------------------------

export interface EchoInputs {
  q1Paraphrase: string;
  q2Verbatim: string;
  q3Paraphrase: string;
  q4Verbatim: string;
  q5Paraphrase: string;
}

export function renderEchoBody(e: EchoInputs): ReadonlyArray<string> {
  return [
    `You're ${e.q1Paraphrase}.`,
    `A year from now, the thought that hits you is: ${e.q2Verbatim}`,
    `What you actually want — the thing you don't say out loud — is ${e.q3Paraphrase}.`,
    `And the reason it hasn't happened yet? ${e.q4Verbatim}`,
    `You're not browsing. ${e.q5Paraphrase}`,
  ];
}
