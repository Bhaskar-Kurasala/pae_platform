/**
 * Centralized copy for the Mock Interview feature.
 *
 * Tone rules — read these before editing:
 *  1. Warm, direct, evidence-grounded.
 *  2. No hype. No "Awesome!", "Great job!", "You crushed it!".
 *  3. Calibrated honesty — if the agent declines to score, the UI says so plainly.
 *  4. No streak language. No leaderboard language. Ever.
 */

export const COPY = {
  modePicker: {
    eyebrow: "Mock Interview",
    title: "Pick the kind of interview you need to rehearse.",
    blurb:
      "Each mode adapts to the role you target, the level you aim for, and what your platform history says you've actually built. Mock #5 will not feel like mock #1.",
    modes: {
      technical_conceptual: {
        title: "Technical Conceptual",
        timeEstimate: "~12 min",
        example: "Walk me through how you'd design a cache eviction policy.",
        blurb:
          "Concepts, edge cases, trade-offs. Voice or text. No live coding.",
      },
      live_coding: {
        title: "Live Coding",
        timeEstimate: "~20 min",
        example: "Find the first non-repeating character in a string.",
        blurb:
          "Editor + agent on the same screen. The agent watches as you type and probes mid-coding.",
      },
      behavioral: {
        title: "Behavioral",
        timeEstimate: "~15 min",
        example: "Tell me about a time a code review changed how you thought about a problem.",
        blurb:
          "STAR-shaped questions. Voice mode recommended — fillers and pace are measured.",
      },
      system_design: {
        title: "System Design",
        timeEstimate: "Phase 2",
        example: "Coming soon.",
        blurb: "Reserved for Phase 2.",
        disabled: true,
      },
    },
  },
  preSession: {
    title: "Quick setup before we start.",
    targetRoleLabel: "Target role",
    targetRolePlaceholder: "e.g., Junior Python Backend Engineer",
    levelLabel: "Level you're targeting",
    jdLabel: "Optional — paste the JD",
    jdPlaceholder:
      "Paste the full JD here. The agent will tune questions to its requirements.",
    voiceLabel: "Voice mode",
    voiceHelp:
      "Voice mode measures filler words and pace. Recommended for Behavioral and Conceptual modes.",
    startButton: "Start mock interview",
  },
  session: {
    interviewerName: "Interviewer",
    youName: "You",
    typeHint: "Type your answer — or hit the mic to speak.",
    voiceHint: "Press to speak. Release when done.",
    endButton: "End session",
    endConfirm:
      "End the session now? You'll get a partial report with what's been answered so far.",
    costNotice: (inr: number) =>
      `Session cost so far: ₹${inr.toFixed(2)} of ₹40 cap.`,
    costCapHit:
      "We've reached the per-session cost cap. End the session to see your report.",
    needsHumanReview:
      "I'd recommend a human review on this answer — my confidence isn't high enough to score it fairly.",
    interruptHint:
      "If the interviewer interrupts you, that's a signal — not a punishment.",
  },
  report: {
    title: "Session debrief",
    headlineEyebrow: "Headline",
    verdictLabels: {
      would_pass: "Would pass",
      borderline: "Borderline",
      would_not_pass: "Would not pass",
      needs_human_review: "Needs human review",
    } as Record<string, string>,
    rubricEyebrow: "Per-criterion scores",
    patternsEyebrow: "Patterns the mic picked up",
    strengthsEyebrow: "What worked",
    weaknessesEyebrow: "What didn't land",
    nextActionEyebrow: "One thing to do next",
    confidenceLowBanner:
      "The post-mortem couldn't be generated with high confidence. Treat the rubric numbers below as directional — not authoritative.",
    shareButton: "Share read-only link",
    shareCopied: "Link copied — read-only.",
    transcriptEyebrow: "Transcript",
    transcriptCollapsed: "Show full transcript",
    transcriptExpanded: "Hide transcript",
  },
  liveCoding: {
    runButton: "Run",
    runHint: "Code runs in your browser via Pyodide — nothing is sent to the server until you submit.",
    stuck: "Submit what you have",
    sandboxLoading: "Loading Python runtime…",
  },
  errors: {
    startFailed: "Couldn't start the session. Try again in a moment.",
    answerFailed: "Couldn't evaluate that answer. Try resubmitting.",
    completeFailed: "Couldn't finalize the report. The session is saved — open it from your history.",
    micDenied: "Microphone access was denied. Switching to text mode.",
    sttUnsupported:
      "Voice input isn't available in this browser. Switching to text mode.",
  },
};

export const ANALYTICS_EVENTS = {
  SESSION_STARTED: "mock.session.started",
  SESSION_COMPLETED: "mock.session.completed",
  SESSION_ABANDONED: "mock.session.abandoned",
  REPORT_VIEWED: "mock.report.viewed",
  REPORT_SHARED: "mock.report.shared",
  NEXT_ACTION_CLICKED: "mock.next_action.clicked",
  VOICE_FALLBACK_TO_TEXT: "mock.voice.fallback_to_text",
  CONFIDENCE_BELOW_THRESHOLD: "mock.confidence.below_threshold",
} as const;

export type MockAnalyticsEvent =
  (typeof ANALYTICS_EVENTS)[keyof typeof ANALYTICS_EVENTS];
