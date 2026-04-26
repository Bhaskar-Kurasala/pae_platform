"use client";

import { readinessCopy } from "@/lib/copy/readiness";

interface MemoryBannerProps {
  hint: string | null;
}

/**
 * Gentle continuity surface above the conversation. Small, warm, never
 * loud. Renders nothing for first-time students (hint=null) — the
 * spec is explicit that empty memory shouldn't reach for vague refs.
 *
 * Tone target per spec: "Last time the gap was X. Looks like you've
 * done Y since." Never reproachful, never "you said you would".
 */
export function MemoryBanner({ hint }: MemoryBannerProps) {
  if (!hint) return null;
  return (
    <div
      className="diagnostic-memory-banner"
      role="note"
      aria-label="Continuity from your last session"
      style={{
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        padding: "10px 14px",
        marginBottom: 12,
        borderLeft: "3px solid var(--gold)",
        background: "var(--gold-soft)",
        borderRadius: 6,
        color: "var(--ink)",
        fontSize: 13,
        lineHeight: 1.5,
      }}
    >
      <span
        aria-hidden="true"
        style={{
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: 1.2,
          color: "var(--gold)",
          fontWeight: 600,
          flexShrink: 0,
          paddingTop: 1,
        }}
      >
        {readinessCopy.diagnostic.memoryBannerPrefix}
      </span>
      <span>{hint}</span>
    </div>
  );
}
