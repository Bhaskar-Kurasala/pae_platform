/**
 * Streak = consistency receipt, not gamification.
 *
 * We compute it from the set of days the student had *any* activity timestamp
 * (currently: `last_touched_at` on their skill states). A streak is the number
 * of consecutive calendar days up to and including today (or yesterday — we
 * give a grace window so the streak doesn't "reset" at midnight) with at
 * least one active day in the set.
 */

function toYmd(d: Date): string {
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

export function activeDaySet(timestamps: Array<string | null | undefined>): Set<string> {
  const out = new Set<string>();
  for (const ts of timestamps) {
    if (!ts) continue;
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) continue;
    out.add(toYmd(d));
  }
  return out;
}

export function computeStreak(days: Set<string>, now: Date = new Date()): number {
  if (days.size === 0) return 0;

  const today = toYmd(now);
  const yesterday = toYmd(new Date(now.getTime() - 86400000));

  // Streak "anchor": today if active today, else yesterday (one-day grace).
  let cursor: Date;
  if (days.has(today)) {
    cursor = new Date(now);
  } else if (days.has(yesterday)) {
    cursor = new Date(now.getTime() - 86400000);
  } else {
    return 0;
  }

  let count = 0;
  while (days.has(toYmd(cursor))) {
    count++;
    cursor = new Date(cursor.getTime() - 86400000);
  }
  return count;
}
