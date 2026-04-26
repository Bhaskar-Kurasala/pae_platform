// All user-facing strings for the Tailored Resume feature live here.
// Tone: warm, evidence-grounded, no hype, plainspoken.

export const tailoredResumeCopy = {
  cta: {
    title: "Tailor this resume to a real JD",
    blurb:
      "Paste the job description and we'll rebuild your resume with proof you've already earned on the platform.",
    button: "Generate tailored version",
  },

  intake: {
    stepLabels: ["Job description", "A few questions", "Review"],
    jdHeading: "Paste the job description",
    jdHelper:
      "We'll extract must-haves, nice-to-haves, and tone — used to tailor every bullet.",
    jdPlaceholder:
      "Paste the full JD — requirements, responsibilities, tech stack, everything.",
    questionsHeading: "A few quick questions",
    questionsHelper:
      "We skip anything we already know from your platform activity. These fill in what we can't see.",
    reviewHeading: "Ready to generate",
    reviewHelper:
      "We'll cite only skills and projects you've already proven, plus the experience you've shared with us.",
    generateButton: "Generate resume + cover letter",
    cancelButton: "Cancel",
    backButton: "Back",
    nextButton: "Continue",
  },

  generation: {
    steps: [
      "Reading the JD…",
      "Matching your projects…",
      "Drafting tailored bullets…",
      "Writing the cover letter…",
      "Rendering ATS-safe PDF…",
    ],
    failureTitle: "Something went sideways",
    failureBody:
      "We couldn't finish that generation. Your quota wasn't used. Try again, or cancel and come back.",
  },

  preview: {
    heading: "Tailored resume",
    coverLetterHeading: "Cover letter",
    downloadButton: "Download PDF",
    logApplicationButton: "Log this application",
    closeButton: "Close",
    validationPassed: "Every claim in this resume traces back to your verified evidence.",
    validationWarn:
      "We had to relax the source check on a few items — review carefully before sending.",
  },

  quota: {
    chipFreeFirst: "First resume free",
    chipWithin: (today: number, total: number) =>
      `${today} of ${total} today`,
    chipMonth: (month: number, total: number) =>
      `${month} of ${total} this month`,
    blockedDaily: "You've hit today's free limit. Resets at midnight.",
    blockedMonthly: "You've used this month's free quota.",
    upgradeNudge: "Tailoring more than 5 a day? Premium removes the limits.",
  },

  softGate: {
    title: "You're close — but not quite ready to apply yet",
    body:
      "Your readiness score is still building. Tailoring resumes now is fine, but interviews tend to convert better once you've closed one more capstone or mock.",
    overrideButton: "I want to apply anyway",
    rehearseButton: "Rehearse first",
  },
} as const;
