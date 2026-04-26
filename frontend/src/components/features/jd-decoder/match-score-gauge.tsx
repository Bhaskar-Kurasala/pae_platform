"use client";

import type { CSSProperties } from "react";

import { readinessCopy } from "@/lib/copy/readiness";

interface MatchScoreGaugeProps {
  score: number | null;
  headline: string;
}

/**
 * Match-score visual using the existing --forest / --gold token system.
 * The gauge is a 320x180 SVG arc; the score sits in the center in a
 * Fraunces-serif weight to match the readiness page's headline rhythm.
 *
 * When the score is null (thin-data student), the gauge renders a
 * neutral arc and surfaces the "not enough activity" headline instead
 * of a number.
 */
export function MatchScoreGauge({ score, headline }: MatchScoreGaugeProps) {
  const hasScore = typeof score === "number";
  const clamped = hasScore ? Math.max(0, Math.min(100, score)) : 0;

  // Arc geometry — 180° sweep from -90° to 90°.
  const r = 120;
  const cx = 160;
  const cy = 150;
  const startAngle = Math.PI; // 180°
  const endAngle =
    Math.PI + (clamped / 100) * Math.PI; // up to 360°

  const arcPath = (angle: number) => {
    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(angle);
    const y2 = cy + r * Math.sin(angle);
    const large = angle - startAngle > Math.PI ? 1 : 0;
    return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
  };

  const trackColor = "var(--forest-soft)";
  const fillColor = hasScore ? "var(--forest-3)" : "var(--ink-2)";

  const labelStyle: CSSProperties = {
    fontFamily: "var(--serif, 'Fraunces', Georgia, serif)",
    fontSize: 56,
    fontWeight: 600,
    fill: "var(--ink)",
  };

  return (
    <div className="match-score-gauge">
      <svg
        viewBox="0 0 320 180"
        width="100%"
        height="auto"
        role="img"
        aria-label={
          hasScore
            ? `Match score ${clamped} out of 100`
            : readinessCopy.jd.matchThinDataNote
        }
      >
        <path
          d={arcPath(2 * Math.PI)}
          fill="none"
          stroke={trackColor}
          strokeWidth={18}
          strokeLinecap="round"
        />
        {hasScore && clamped > 0 && (
          <path
            d={arcPath(endAngle)}
            fill="none"
            stroke={fillColor}
            strokeWidth={18}
            strokeLinecap="round"
          />
        )}
        <text
          x={cx}
          y={cy - 8}
          textAnchor="middle"
          style={labelStyle}
        >
          {hasScore ? `${clamped}` : "—"}
        </text>
        <text
          x={cx}
          y={cy + 18}
          textAnchor="middle"
          style={{
            fontFamily: "var(--font-inter, Inter, system-ui)",
            fontSize: 12,
            fill: "var(--ink-2)",
            letterSpacing: 1.2,
            textTransform: "uppercase",
          }}
        >
          {hasScore
            ? readinessCopy.jd.matchScoreLabel
            : readinessCopy.jd.matchThinDataNote}
        </text>
      </svg>
      {hasScore && (
        <div
          className="match-score-headline"
          style={{
            fontFamily: "var(--serif, 'Fraunces', Georgia, serif)",
            fontSize: 18,
            color: "var(--ink)",
            marginTop: 8,
            textAlign: "center",
          }}
        >
          {headline}
        </div>
      )}
    </div>
  );
}
