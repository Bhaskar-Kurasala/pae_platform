/**
 * F10 — Calendar mailto-shim.
 *
 * The full Cal.com / Google OAuth integration is deferred (see
 * docs/RETENTION-ENGINE.md F10). Until we have >20 paid students,
 * a real calendar invite isn't worth the OAuth dance — admins
 * negotiate call times over email anyway. This helper builds an
 * RFC6068 mailto: URL with the slip context pre-filled so the
 * "Schedule call" button on /admin/* opens the operator's mail
 * client with a thoughtful first draft, not a blank canvas.
 *
 * Tone: short, friendly, references the specific slip pattern so
 * the student knows we noticed something specific (not a form
 * letter). No corporate speak. Single-line subject so it doesn't
 * truncate awkwardly in inbox previews.
 */
const SLIP_LABELS: Record<string, string> = {
  paid_silent: "the AI engineer track",
  capstone_stalled: "your capstone",
  streak_broken: "your daily session streak",
  promotion_avoidant: "your senior review",
  cold_signup: "getting started",
  unpaid_stalled: "the platform",
};

const SLIP_OPENERS: Record<string, string> = {
  paid_silent:
    "I noticed you've been quiet for a bit since you signed up — I'd like to make sure the platform is actually working for you.",
  capstone_stalled:
    "I noticed your capstone draft has been sitting for a while and wanted to see what's blocking it. Capstones are where most people get stuck — that's normal.",
  streak_broken:
    "Your streak broke and I wanted to check in before too much momentum is lost. No pressure — just curious whether life pulled you away or something on the platform did.",
  promotion_avoidant:
    "You passed senior review but haven't claimed the gate yet. Wanted to nudge you across the line and see if I can help.",
  cold_signup:
    "Wanted to check in since you signed up — first session is the highest-leverage moment, and I'd like to help you get to it.",
  unpaid_stalled:
    "Wanted to check in — you got past the first session but haven't been back. Curious what's holding you up.",
};

export interface BuildCallInviteMailtoArgs {
  studentEmail: string;
  studentName?: string | null;
  slipType?: string | null;
  /**
   * Free-text reason from `risk_panels.risk_reason` or any short
   * context line the admin wants embedded. Appended after the slip
   * opener so the body reads as one continuous note.
   */
  riskReason?: string | null;
}

/**
 * Returns a `mailto:` URL with subject + body URL-encoded.
 *
 * Throws if studentEmail is missing — a button that opens an empty
 * mailto: is worse than no button.
 */
export function buildCallInviteMailto(args: BuildCallInviteMailtoArgs): string {
  const { studentEmail, studentName, slipType, riskReason } = args;
  if (!studentEmail || !studentEmail.trim()) {
    throw new Error("studentEmail is required to build a call invite mailto");
  }

  const firstName = (studentName ?? "").split(" ")[0]?.trim() || "there";
  const slipLabel = slipType ? SLIP_LABELS[slipType] ?? null : null;
  const opener =
    (slipType && SLIP_OPENERS[slipType]) ??
    "Wanted to set up a quick call so I can hear what's working on the platform and what isn't.";

  const subject = slipLabel
    ? `Quick call about ${slipLabel}?`
    : "Quick call?";

  const lines: string[] = [
    `Hey ${firstName},`,
    "",
    opener,
  ];
  if (riskReason && riskReason.trim()) {
    lines.push("", `(For context on my end: ${riskReason.trim()}.)`);
  }
  lines.push(
    "",
    "I have 15 minutes free this week — would Tuesday or Thursday work for you? Reply with a time that fits and I'll send a calendar invite.",
    "",
    "—Bhaskar",
  );

  const body = lines.join("\n");
  const params = new URLSearchParams({ subject, body });
  // URLSearchParams encodes spaces as `+`. RFC 6068 says either is
  // acceptable, but `%20` is what every modern mail client expects
  // in mailto: bodies — Outlook in particular renders the `+` as
  // a literal plus sign. Swap it back.
  const query = params.toString().replace(/\+/g, "%20");
  return `mailto:${encodeURIComponent(studentEmail.trim())}?${query}`;
}
