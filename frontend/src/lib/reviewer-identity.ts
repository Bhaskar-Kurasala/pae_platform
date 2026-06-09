/**
 * Reviewer persona for the senior-review panel — single source of truth.
 *
 * Every senior-review message is presented as if it came from Bhaskar K,
 * AICareerOS's founding senior engineer. The voice and review style is
 * his; the drafting is automated. Surfaces that need to render the
 * reviewer's identity should import from here so changing the persona
 * (renaming, swapping the avatar style, adding a second persona later)
 * is a one-file edit.
 */

export interface ReviewerIdentity {
  /** Full display name as it appears in the chat header. */
  fullName: string;
  /** Two-letter initials used inside the avatar circle. */
  initials: string;
  /** Role / title shown directly under the name. */
  role: string;
  /** Organization affiliation appended after the role with a dot. */
  org: string;
  /** Background colors for the avatar circle gradient.
   * Pulled from v8 design tokens at usage time to stay theme-aware;
   * keep the keys generic so a future palette swap is local. */
  avatarFrom: string;
  avatarTo: string;
  /** Foreground (initial-text) color inside the avatar. */
  avatarInk: string;
}

export const SENIOR_REVIEWER: ReviewerIdentity = {
  fullName: "Bhaskar K",
  initials: "BK",
  role: "Senior Engineer",
  org: "AICareerOS",
  avatarFrom: "var(--forest)",
  avatarTo: "var(--forest-2)",
  avatarInk: "#ffffff",
};

/** Format a Date as "Today, 2:47 pm" / "Yesterday, 9:12 am" / "Apr 28, 4:03 pm".
 *
 * The chat header carries a relative-ish timestamp so the review feels
 * like a real message in a thread, not a stamped JSON document. We
 * intentionally avoid the full ISO string — it's too clinical.
 */
export function formatReviewTimestamp(when: Date | string): string {
  const date = typeof when === "string" ? new Date(when) : when;
  if (Number.isNaN(date.getTime())) return "";

  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);

  const time = date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });

  if (date >= startOfToday) return `Today, ${time}`;
  if (date >= startOfYesterday) return `Yesterday, ${time}`;
  return `${date.toLocaleDateString(undefined, { month: "short", day: "numeric" })}, ${time}`;
}
