"use client";

/**
 * <HealthStrip> — sticky 6-tile row at the top of the admin cockpit
 * showing the operator's "things on fire right now" snapshot. Each
 * tile is clickable and opens <HealthDetailModal> for that metric.
 */

import { ArrowDown, ArrowUp } from "lucide-react";
import { useHealthStrip, type HealthMetric } from "@/lib/hooks/use-admin";

interface HealthStripProps {
  pageTheme?: "light" | "dark";
  onTileClick?: (key: string) => void;
}

export function HealthStrip({
  pageTheme = "light",
  onTileClick,
}: HealthStripProps) {
  const { data, isLoading } = useHealthStrip();
  const isDark = pageTheme === "dark";

  const tone = {
    danger: "#d96252",
    warn: "#d6a54d",
    ok: isDark ? "#8fd6b1" : "#356d50",
    neutral: isDark ? "#2c3830" : "#dbd1bf",
  } as const;

  const stripBg = isDark
    ? "linear-gradient(180deg, rgba(15, 22, 18, 0.92), rgba(11, 17, 14, 0.88))"
    : "linear-gradient(180deg, rgba(255, 252, 245, 0.92), rgba(251, 247, 238, 0.88))";
  const tileBg = isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.7)";
  const tileBgHover = isDark
    ? "rgba(255,255,255,0.07)"
    : "rgba(255,255,255,0.95)";
  const line = isDark ? "#2c3830" : "#dbd1bf";
  const ink = isDark ? "#f0ece1" : "#10120e";
  const muted = isDark ? "#9a9588" : "#686559";
  const eyebrow = isDark ? "#8fd6b1" : "#356d50";

  return (
    <div className="cf-health-strip" data-theme={pageTheme}>
      {isLoading || !data
        ? Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="cf-health-tile cf-health-skeleton" />
          ))
        : data.metrics.map((m) => (
            <HealthTile
              key={m.key}
              metric={m}
              accent={tone[m.tone]}
              onClick={() => onTileClick?.(m.key)}
            />
          ))}
      <style>{`
        .cf-health-strip[data-theme="${pageTheme}"] {
          position: sticky;
          top: 52px;
          z-index: 40;
          display: grid;
          grid-template-columns: repeat(6, minmax(0, 1fr));
          gap: 10px;
          padding: 12px 18px;
          background: ${stripBg};
          backdrop-filter: blur(14px) saturate(140%);
          -webkit-backdrop-filter: blur(14px) saturate(140%);
          border-bottom: 1px solid ${line};
          font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
        }
        .cf-health-strip[data-theme="${pageTheme}"] .cf-health-tile {
          position: relative;
          display: flex;
          flex-direction: column;
          gap: 4px;
          padding: 12px 14px 12px 16px;
          background: ${tileBg};
          border: 1px solid ${line};
          border-left-width: 3px;
          border-radius: 12px;
          cursor: pointer;
          text-align: left;
          transition:
            background .18s cubic-bezier(.2,.8,.2,1),
            border-color .18s cubic-bezier(.2,.8,.2,1),
            transform .18s cubic-bezier(.2,.8,.2,1);
          color: ${ink};
        }
        .cf-health-strip[data-theme="${pageTheme}"] .cf-health-tile:hover {
          background: ${tileBgHover};
          transform: translateY(-1px);
        }
        .cf-health-strip[data-theme="${pageTheme}"] .cf-health-tile:focus-visible {
          outline: none;
          box-shadow: 0 0 0 3px ${
            isDark ? "rgba(143,214,177,0.30)" : "rgba(78,148,112,0.22)"
          };
        }
        .cf-health-strip[data-theme="${pageTheme}"] .cf-health-eyebrow {
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.2em;
          text-transform: uppercase;
          color: ${eyebrow};
        }
        .cf-health-strip[data-theme="${pageTheme}"] .cf-health-value {
          font-family: var(--font-fraunces), Georgia, serif;
          font-size: 24px;
          font-weight: 500;
          letter-spacing: -0.02em;
          line-height: 1.1;
          color: ${ink};
        }
        .cf-health-strip[data-theme="${pageTheme}"] .cf-health-sub {
          font-size: 12px;
          line-height: 1.5;
          color: ${muted};
        }
        .cf-health-strip[data-theme="${pageTheme}"] .cf-health-delta {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
          font-size: 11px;
          font-weight: 600;
          letter-spacing: 0.02em;
          font-feature-settings: "tnum";
        }
        .cf-health-strip[data-theme="${pageTheme}"] .cf-health-delta-up {
          color: ${isDark ? "#8fd6b1" : "#356d50"};
        }
        .cf-health-strip[data-theme="${pageTheme}"] .cf-health-delta-down {
          color: #d96252;
        }
        .cf-health-strip[data-theme="${pageTheme}"] .cf-health-skeleton {
          background: ${
            isDark ? "rgba(255,255,255,0.025)" : "rgba(0,0,0,0.025)"
          };
          border-left-color: ${line};
          min-height: 78px;
          animation: cfHealthPulse 1.6s ease-in-out infinite;
          cursor: default;
        }
        .cf-health-strip[data-theme="${pageTheme}"] .cf-health-skeleton:hover {
          background: ${isDark ? "rgba(255,255,255,0.025)" : "rgba(0,0,0,0.025)"};
          transform: none;
        }
        @keyframes cfHealthPulse {
          0%, 100% { opacity: 0.55; }
          50% { opacity: 0.85; }
        }
        @media (max-width: 1100px) {
          .cf-health-strip[data-theme="${pageTheme}"] {
            grid-template-columns: repeat(3, minmax(0, 1fr));
          }
        }
        @media (max-width: 640px) {
          .cf-health-strip[data-theme="${pageTheme}"] {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }
      `}</style>
    </div>
  );
}

function HealthTile({
  metric,
  accent,
  onClick,
}: {
  metric: HealthMetric;
  accent: string;
  onClick: () => void;
}) {
  const isUp = metric.delta != null && metric.delta > 0;
  const isDown = metric.delta != null && metric.delta < 0;
  return (
    <button
      type="button"
      className="cf-health-tile"
      style={{ borderLeftColor: accent }}
      onClick={onClick}
      aria-label={`${metric.label}: ${metric.value}. ${metric.sub}`}
    >
      <span className="cf-health-eyebrow">{metric.label}</span>
      <span className="cf-health-value">{metric.value}</span>
      <span className="cf-health-sub">
        {metric.sub}
        {metric.delta_text ? (
          <>
            {" "}
            <span
              className={
                isUp
                  ? "cf-health-delta cf-health-delta-up"
                  : isDown
                    ? "cf-health-delta cf-health-delta-down"
                    : "cf-health-delta"
              }
            >
              {isUp ? (
                <ArrowUp size={11} strokeWidth={2.4} />
              ) : isDown ? (
                <ArrowDown size={11} strokeWidth={2.4} />
              ) : null}
              {metric.delta_text}
            </span>
          </>
        ) : null}
      </span>
    </button>
  );
}
