"use client";

/**
 * Renders an inline [PLACEHOLDER] tag in dev/staging only when a stat is
 * unverified. Hides automatically in production builds. The badge exists so
 * unverified stats can't accidentally ship — it's loud, in-band, and matches
 * the surrounding text color exactly so it survives a dark/light flip.
 */
export function PlaceholderBadge({ verified }: { verified: boolean }) {
  if (verified) return null;
  if (process.env.NODE_ENV === "production") return null;
  return (
    <span
      className="ml-1.5 inline-block rounded-sm border border-amber-500/60 bg-amber-500/15 px-1.5 py-[1px] align-middle font-mono text-[9px] font-bold uppercase tracking-[0.08em] text-amber-300"
      title="This statistic is unverified. Set `verified: true` in _quiz-config.ts after ops confirms with real data."
    >
      placeholder
    </span>
  );
}
