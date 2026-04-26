/**
 * Shared user-facing strings for the Job Readiness page.
 *
 * Consolidating copy here enforces the page's voice across the diagnostic
 * conversation, JD decoder, and verdict cards. The voice rules
 * (warm + direct, evidence-grounded, calm, never sycophantic) are
 * defined in `docs/features/job-readiness-page-strategy.md` §11. When
 * editing strings, re-read that section.
 */

export const readinessCopy = {
  // ── JD Decoder ──────────────────────────────────────────────────
  jd: {
    cardTitle: "Decode a JD",
    cardBlurb:
      "Paste a job description. We'll separate the real must-haves from the wishlist, flag the language patterns worth probing, and tell you where you stand against this specific role.",
    pasteLabel: "Paste the job description",
    pastePlaceholder: "Paste the JD text here…",
    submitLabel: "Decode",
    submitPendingLabel: "Reading the JD…",
    error: "Couldn't decode that JD. Try a different paste, or come back in a minute.",
    tooShortError:
      "That looks too short to be a real JD — paste the full posting.",
    sectionMustHaves: "Real must-haves",
    sectionMustHavesBlurb:
      "Skills the team will actually screen for. Stripped of inflation.",
    sectionWishlist: "Wishlist",
    sectionWishlistBlurb:
      "Strengthens your match but won't gate you out.",
    sectionFiller: "Template language",
    sectionFillerBlurb:
      "Phrases the JD uses that mean less than they look like they do.",
    sectionCulture: "Culture signals",
    sectionCultureBlurb:
      "Patterns commonly seen in JDs — read for nuance, not as accusations.",
    inflatedWishlistFlag: "This JD lists more must-haves than is plausible.",
    seniorityHeader: "Seniority read",
    matchScoreLabel: "Match against your verified work",
    matchThinDataNote:
      "Not enough activity yet to score this match honestly.",
    matchHeadlineFallback: "Match scored.",
  },

  // ── Diagnostic conversation (used in commit 8) ──────────────────
  diagnostic: {
    opener:
      "Tell me where you're at — I'll tell you where you stand. Honest, evidence-grounded, no flattery.",
    typingIndicator: "Reading your work…",
    finalizingIndicator: "Pulling the picture together…",
    inputPlaceholder: "Type what's on your mind…",
    sendLabel: "Send",
    nextActionPrompt: "Here's the one thing to do next.",
    pastDiagnosesLink: "View past diagnoses",
    softCapNote:
      "Let's bring this in. Here's what I'm seeing.",
    errorGeneric:
      "Something dropped on our side. Send your last message again.",
    memoryBannerPrefix: "Last time —",
    // Inline decoder embed (commit 9 — diagnostic ↔ decoder bundle).
    decoderEmbedHeader: "Paste the JD",
    decoderEmbedBlurb:
      "I'll read it against your verified work and bring the result back into the conversation.",
  },
} as const;

export type ReadinessCopy = typeof readinessCopy;
