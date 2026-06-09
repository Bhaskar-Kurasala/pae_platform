"use client";

/**
 * <HealthStrip> — premium bento-grid health snapshot at the top of the
 * admin cockpit. Renders one large "hero" tile (the most urgent metric),
 * one supporting small tile, the cohort-delta tile (always in the row-1
 * right slot), and four small tiles in row 2. Sparklines render inline
 * from the backend's sparkline_7d field; the cohort tile uses a mini
 * bar chart instead.
 *
 * Click → onTileClick(metric.key) opens the existing detail modal.
 */

import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  Brain,
  CheckCircle2,
  DollarSign,
  MessageSquare,
  MoonStar,
  Sparkles,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import { useHealthStrip, type HealthMetric } from "@/lib/hooks/use-admin";

interface HealthStripProps {
  pageTheme?: "light" | "dark";
  onTileClick?: (key: string) => void;
}

type Tone = HealthMetric["tone"];

interface TonePalette {
  bg: string;
  bgDark: string;
  stroke: string;
  pill: string | null;
  ink: string;
}

const TONE_MAP: Record<Tone, TonePalette> = {
  danger: {
    bg: "rgba(217,98,82,0.06)",
    bgDark: "rgba(217,98,82,0.10)",
    stroke: "#d96252",
    pill: "URGENT",
    ink: "#d96252",
  },
  warn: {
    bg: "rgba(214,165,77,0.06)",
    bgDark: "rgba(214,165,77,0.10)",
    stroke: "#d6a54d",
    pill: "WATCH",
    ink: "#d6a54d",
  },
  ok: {
    bg: "rgba(29,158,117,0.04)",
    bgDark: "rgba(29,158,117,0.10)",
    stroke: "#1D9E75",
    pill: "OK",
    ink: "#1D9E75",
  },
  neutral: {
    bg: "rgba(0,0,0,0.02)",
    bgDark: "rgba(255,255,255,0.04)",
    stroke: "#8f897d",
    pill: null,
    ink: "#8f897d",
  },
};

const ICON_MAP: Record<string, LucideIcon> = {
  revenue_at_risk: DollarSign,
  review_queue: CheckCircle2,
  top_confusion: Brain,
  worst_lessons: BookOpen,
  stale_students: MoonStar,
  open_feedback: MessageSquare,
  cohort_delta: TrendingUp,
};

const HERO_TIEBREAKER: Record<string, number> = {
  stale_students: 6,
  review_queue: 5,
  worst_lessons: 4,
  top_confusion: 3,
  open_feedback: 2,
  revenue_at_risk: 1,
};

function parseNumeric(value: string): number {
  const cleaned = value.replace(/[^0-9.\-]/g, "");
  const n = parseFloat(cleaned);
  return Number.isFinite(n) ? n : 0;
}

function pickHero(candidates: HealthMetric[]): HealthMetric | null {
  if (candidates.length === 0) return null;
  const score = (m: HealthMetric): [number, number, number] => {
    const toneRank =
      m.tone === "danger" ? 3 : m.tone === "warn" ? 2 : m.tone === "ok" ? 0 : 1;
    const value = parseNumeric(m.value);
    const tie = HERO_TIEBREAKER[m.key] ?? 0;
    return [toneRank, value, tie];
  };
  const sorted = [...candidates].sort((a, b) => {
    const sa = score(a);
    const sb = score(b);
    if (sa[0] !== sb[0]) return sb[0] - sa[0];
    if (sa[1] !== sb[1]) return sb[1] - sa[1];
    return sb[2] - sa[2];
  });
  // If nothing is danger/warn, prefer stale_students or revenue_at_risk.
  const top = sorted[0];
  if (top.tone === "danger" || top.tone === "warn") return top;
  const stale = candidates.find((m) => m.key === "stale_students");
  if (stale) return stale;
  const rev = candidates.find((m) => m.key === "revenue_at_risk");
  if (rev) return rev;
  return top;
}

interface SparklineProps {
  data: number[] | undefined;
  width: number;
  height: number;
  stroke: string;
  fillOpacity?: number;
  strokeWidth?: number;
}

function Sparkline({
  data,
  width,
  height,
  stroke,
  fillOpacity = 0.2,
  strokeWidth = 2,
}: SparklineProps) {
  if (!data || data.length === 0) {
    return (
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <line
          x1="0"
          y1={height / 2}
          x2={width}
          y2={height / 2}
          stroke={stroke}
          strokeOpacity={0.3}
          strokeDasharray="2 3"
          strokeWidth={1}
        />
      </svg>
    );
  }
  const n = data.length;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = strokeWidth;
  const innerH = height - pad * 2;
  const stepX = n > 1 ? width / (n - 1) : 0;
  const points = data.map((v, i) => {
    const x = n > 1 ? i * stepX : width / 2;
    const y =
      max === min ? height / 2 : pad + innerH - ((v - min) / range) * innerH;
    return [x, y] as const;
  });
  const linePath = points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
    .join(" ");
  const areaPath = `${linePath} L${width.toFixed(2)},${height} L0,${height} Z`;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <path d={areaPath} fill={stroke} fillOpacity={fillOpacity} />
      <path
        d={linePath}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface BarChartProps {
  data: number[] | undefined;
  width: number;
  height: number;
  color: string;
}

function BarChart({ data, width, height, color }: BarChartProps) {
  if (!data || data.length === 0) {
    return (
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <line
          x1="0"
          y1={height - 1}
          x2={width}
          y2={height - 1}
          stroke={color}
          strokeOpacity={0.3}
          strokeDasharray="2 3"
        />
      </svg>
    );
  }
  const n = data.length;
  const max = Math.max(...data, 1);
  const gap = 4;
  const barW = Math.max(2, (width - gap * (n - 1)) / n);
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {data.map((v, i) => {
        const h = Math.max(2, (Math.abs(v) / max) * (height - 2));
        const x = i * (barW + gap);
        const y = height - h;
        const r = Math.min(barW / 2, 3);
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={barW}
            height={h}
            rx={r}
            ry={r}
            fill={color}
            opacity={0.85}
          />
        );
      })}
    </svg>
  );
}

function DeltaPill({
  metric,
  isDark,
  size = "sm",
}: {
  metric: HealthMetric;
  isDark: boolean;
  size?: "sm" | "xs";
}) {
  if (!metric.delta_text) return null;
  const isUp = metric.delta != null && metric.delta > 0;
  const isDown = metric.delta != null && metric.delta < 0;
  const color = isUp
    ? isDark
      ? "#8fd6b1"
      : "#1D9E75"
    : isDown
      ? "#d96252"
      : isDark
        ? "#9a9588"
        : "#686559";
  const px = size === "xs" ? 10 : 11;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 3,
        fontSize: px,
        fontWeight: 600,
        fontFamily:
          "var(--font-jetbrains-mono), ui-monospace, monospace",
        color,
        letterSpacing: "0.02em",
        fontFeatureSettings: '"tnum"',
      }}
    >
      {isUp ? (
        <ArrowUp size={px} strokeWidth={2.4} />
      ) : isDown ? (
        <ArrowDown size={px} strokeWidth={2.4} />
      ) : null}
      {metric.delta_text}
    </span>
  );
}

export function HealthStrip({
  pageTheme = "light",
  onTileClick,
}: HealthStripProps) {
  const { data, isLoading } = useHealthStrip();
  const isDark = pageTheme === "dark";

  const line = isDark ? "#2c3830" : "#dbd1bf";
  const ink = isDark ? "#f0ece1" : "#10120e";
  const muted = isDark ? "#9a9588" : "#686559";
  const eyebrow = isDark ? "#8fd6b1" : "#356d50";
  const stripBg = isDark
    ? "linear-gradient(180deg, rgba(15, 22, 18, 0.92), rgba(11, 17, 14, 0.88))"
    : "linear-gradient(180deg, rgba(255, 252, 245, 0.92), rgba(251, 247, 238, 0.88))";

  // ── Layout assignment ────────────────────────────────────────────
  let hero: HealthMetric | null = null;
  let supporting: HealthMetric | null = null;
  let cohort: HealthMetric | null = null;
  let rowTwo: HealthMetric[] = [];

  if (data && data.metrics.length > 0) {
    const all = data.metrics;
    cohort = all.find((m) => m.key === "cohort_delta") ?? null;
    const remaining = all.filter((m) => m.key !== "cohort_delta");
    hero = pickHero(remaining);
    const afterHero = remaining.filter((m) => m.key !== hero?.key);
    supporting = pickHero(afterHero);
    rowTwo = afterHero.filter((m) => m.key !== supporting?.key);
  }

  const renderSmallTile = (
    metric: HealthMetric,
    key: string,
    spanClass: string,
  ) => {
    const palette = TONE_MAP[metric.tone];
    const Icon = ICON_MAP[metric.key] ?? Sparkles;
    return (
      <button
        type="button"
        key={key}
        className={`cf-bento-tile cf-bento-small ${spanClass}`}
        style={{
          background: isDark ? palette.bgDark : palette.bg,
          borderColor: line,
          color: ink,
        }}
        onClick={() => onTileClick?.(metric.key)}
        aria-label={`${metric.label}: ${metric.value}. ${metric.sub}`}
      >
        <div className="cf-bento-row-top">
          <div className="cf-bento-eyebrow-group">
            <Icon size={12} strokeWidth={2} color={palette.stroke} />
            <span className="cf-bento-eyebrow" style={{ color: eyebrow }}>
              {metric.label}
            </span>
          </div>
          <DeltaPill metric={metric} isDark={isDark} size="xs" />
        </div>
        <div className="cf-bento-row-mid">
          <span
            className="cf-bento-value-sm"
            style={{ color: palette.ink }}
          >
            {metric.value}
          </span>
          <div className="cf-bento-spark-sm">
            <Sparkline
              data={metric.sparkline_7d}
              width={60}
              height={14}
              stroke={palette.stroke}
              strokeWidth={1.5}
              fillOpacity={0.18}
            />
          </div>
        </div>
        <div className="cf-bento-sub" style={{ color: muted }}>
          {metric.sub}
        </div>
      </button>
    );
  };

  const renderHero = (metric: HealthMetric) => {
    const palette = TONE_MAP[metric.tone];
    const Icon = ICON_MAP[metric.key] ?? Sparkles;
    return (
      <button
        type="button"
        className="cf-bento-tile cf-bento-hero cf-span-6"
        style={{
          background: isDark ? palette.bgDark : palette.bg,
          borderColor: line,
          color: ink,
        }}
        onClick={() => onTileClick?.(metric.key)}
        aria-label={`${metric.label}: ${metric.value}. ${metric.sub}`}
      >
        <div className="cf-bento-row-top">
          <div className="cf-bento-eyebrow-group">
            <Icon size={14} strokeWidth={2} color={palette.stroke} />
            <span className="cf-bento-eyebrow" style={{ color: eyebrow }}>
              {metric.label}
            </span>
            {palette.pill ? (
              <span
                className="cf-bento-pill"
                style={{
                  color: palette.stroke,
                  borderColor: palette.stroke,
                  background: isDark ? palette.bgDark : palette.bg,
                }}
              >
                {palette.pill}
              </span>
            ) : null}
          </div>
          <DeltaPill metric={metric} isDark={isDark} size="sm" />
        </div>
        <div className="cf-bento-hero-mid">
          <div
            className="cf-bento-value-hero"
            style={{ color: palette.ink }}
          >
            {metric.value}
          </div>
          <div className="cf-bento-sub" style={{ color: muted }}>
            {metric.sub}
          </div>
        </div>
        <div className="cf-bento-spark-hero">
          <Sparkline
            data={metric.sparkline_7d}
            width={300}
            height={40}
            stroke={palette.stroke}
            strokeWidth={2.5}
            fillOpacity={0.2}
          />
        </div>
        <div
          className="cf-bento-cta"
          style={{ color: eyebrow }}
        >
          Open detail →
        </div>
      </button>
    );
  };

  const renderCohort = (metric: HealthMetric) => {
    const palette = TONE_MAP[metric.tone];
    const Icon = ICON_MAP.cohort_delta;
    const isPositive = (metric.delta ?? 0) >= 0;
    const barColor = isPositive ? "#1D9E75" : "#d96252";
    return (
      <button
        type="button"
        className="cf-bento-tile cf-bento-cohort cf-span-3"
        style={{
          background: isDark ? palette.bgDark : palette.bg,
          borderColor: line,
          color: ink,
        }}
        onClick={() => onTileClick?.(metric.key)}
        aria-label={`Cohort delta: ${metric.delta_text ?? metric.value}. ${metric.sub}`}
      >
        <div className="cf-bento-row-top">
          <div className="cf-bento-eyebrow-group">
            <Icon size={12} strokeWidth={2} color={barColor} />
            <span className="cf-bento-eyebrow" style={{ color: eyebrow }}>
              Cohort delta
            </span>
          </div>
          <DeltaPill metric={metric} isDark={isDark} size="xs" />
        </div>
        <div
          className="cf-bento-value-cohort"
          style={{ color: barColor }}
        >
          {metric.delta_text ?? metric.value}
        </div>
        <div className="cf-bento-cohort-chart">
          <BarChart
            data={metric.sparkline_7d}
            width={200}
            height={60}
            color={barColor}
          />
        </div>
        <div className="cf-bento-sub" style={{ color: muted }}>
          {metric.sub}
        </div>
      </button>
    );
  };

  const renderSkeleton = (
    key: string,
    spanClass: string,
    extraClass: string,
  ) => (
    <div
      key={key}
      className={`cf-bento-tile cf-bento-skeleton ${spanClass} ${extraClass}`}
      style={{ borderColor: line }}
      aria-hidden="true"
    />
  );

  return (
    <div className="cf-bento-strip" data-theme={pageTheme}>
      {isLoading || !data ? (
        <>
          {renderSkeleton("sk-hero", "cf-span-6", "cf-bento-skeleton-hero")}
          {renderSkeleton("sk-r1a", "cf-span-3", "cf-bento-skeleton-small")}
          {renderSkeleton("sk-r1b", "cf-span-3", "cf-bento-skeleton-small")}
          {renderSkeleton("sk-r2a", "cf-span-3", "cf-bento-skeleton-small")}
          {renderSkeleton("sk-r2b", "cf-span-3", "cf-bento-skeleton-small")}
          {renderSkeleton("sk-r2c", "cf-span-3", "cf-bento-skeleton-small")}
          {renderSkeleton("sk-r2d", "cf-span-3", "cf-bento-skeleton-small")}
        </>
      ) : (
        <>
          {hero ? renderHero(hero) : null}
          {supporting
            ? renderSmallTile(supporting, "supp", "cf-span-3 cf-row-1-mid")
            : null}
          {cohort ? renderCohort(cohort) : null}
          {rowTwo.map((m) =>
            renderSmallTile(m, m.key, "cf-span-3"),
          )}
        </>
      )}
      <style>{`
        .cf-bento-strip[data-theme="${pageTheme}"] {
          display: grid;
          grid-template-columns: repeat(12, minmax(0, 1fr));
          grid-auto-rows: minmax(110px, auto);
          gap: 12px;
          padding: 20px 28px 8px;
          max-width: 1640px;
          margin: 0 auto;
          background: transparent;
          font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
        }
        @media (max-width: 1240px) {
          .cf-bento-strip[data-theme="${pageTheme}"] {
            padding: 16px 20px 8px;
          }
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-span-6 { grid-column: span 6; }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-span-3 { grid-column: span 3; }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-tile {
          position: relative;
          display: flex;
          flex-direction: column;
          border: 1px solid ${line};
          border-radius: 12px;
          cursor: pointer;
          text-align: left;
          transition:
            transform .18s cubic-bezier(.2,.8,.2,1),
            box-shadow .18s cubic-bezier(.2,.8,.2,1),
            border-color .18s cubic-bezier(.2,.8,.2,1);
          padding: 16px;
          font: inherit;
          color: inherit;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-tile:hover {
          transform: translateY(-1px);
          box-shadow: 0 6px 18px ${isDark ? "rgba(0,0,0,0.35)" : "rgba(16,18,14,0.08)"};
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-tile:focus-visible {
          outline: none;
          box-shadow: 0 0 0 3px ${isDark ? "rgba(143,214,177,0.30)" : "rgba(78,148,112,0.22)"};
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-hero {
          padding: 20px;
          border-radius: 16px;
          min-height: 180px;
          gap: 10px;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-small,
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-cohort {
          min-height: 110px;
          gap: 6px;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-row-top {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-eyebrow-group {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          min-width: 0;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-eyebrow {
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.18em;
          text-transform: uppercase;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-pill {
          font-size: 9px;
          font-weight: 700;
          letter-spacing: 0.16em;
          padding: 2px 6px;
          border-radius: 999px;
          border: 1px solid;
          text-transform: uppercase;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-hero-mid {
          display: flex;
          flex-direction: column;
          gap: 2px;
          margin-top: 2px;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-value-hero {
          font-family: var(--font-fraunces), Georgia, serif;
          font-size: 48px;
          font-weight: 500;
          letter-spacing: -0.04em;
          line-height: 1;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-value-sm {
          font-family: var(--font-fraunces), Georgia, serif;
          font-size: 24px;
          font-weight: 500;
          letter-spacing: -0.03em;
          line-height: 1.1;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-value-cohort {
          font-family: var(--font-fraunces), Georgia, serif;
          font-size: 28px;
          font-weight: 500;
          letter-spacing: -0.03em;
          line-height: 1.1;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-row-mid {
          display: flex;
          align-items: flex-end;
          justify-content: space-between;
          gap: 10px;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-spark-sm {
          flex: 0 0 auto;
          width: 60px;
          height: 14px;
          display: flex;
          align-items: flex-end;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-spark-hero {
          width: 100%;
          height: 40px;
          margin-top: auto;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-cohort-chart {
          width: 100%;
          height: 60px;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-sub {
          font-size: 12px;
          line-height: 1.45;
          font-weight: 400;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-hero .cf-bento-sub {
          font-size: 13px;
          white-space: normal;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-small .cf-bento-sub {
          font-size: 11px;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-cta {
          position: absolute;
          right: 16px;
          bottom: 12px;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-skeleton {
          cursor: default;
          background: ${
            isDark ? "rgba(255,255,255,0.025)" : "rgba(0,0,0,0.025)"
          };
          animation: cfBentoPulse 1.6s ease-in-out infinite;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-skeleton-hero {
          min-height: 180px;
          border-radius: 16px;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-skeleton-small {
          min-height: 110px;
        }
        .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-skeleton:hover {
          transform: none;
          box-shadow: none;
        }
        @keyframes cfBentoPulse {
          0%, 100% { opacity: 0.55; }
          50% { opacity: 0.85; }
        }
        @media (max-width: 1099px) {
          .cf-bento-strip[data-theme="${pageTheme}"] .cf-span-6,
          .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-hero,
          .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-skeleton-hero {
            grid-column: span 12;
          }
          .cf-bento-strip[data-theme="${pageTheme}"] .cf-span-3,
          .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-skeleton-small {
            grid-column: span 6;
          }
        }
        @media (max-width: 767px) {
          .cf-bento-strip[data-theme="${pageTheme}"] {
            padding: 12px 14px;
            gap: 10px;
          }
          .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-hero,
          .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-cohort,
          .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-skeleton-hero {
            grid-column: span 12;
          }
          .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-small,
          .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-skeleton-small {
            grid-column: span 6;
          }
          .cf-bento-strip[data-theme="${pageTheme}"] .cf-bento-value-hero {
            font-size: 40px;
          }
        }
      `}</style>
    </div>
  );
}
