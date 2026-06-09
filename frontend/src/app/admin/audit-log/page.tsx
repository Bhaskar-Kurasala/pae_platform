"use client";

/**
 * /admin/audit-log — 3-tab admin audit cockpit.
 *
 *  PULSE     — KPI strip + 24h stacked sparkline + category/actor/resource
 *              breakdowns + hot critical actions feed.
 *  STREAM    — original filterable / expandable audit list (preserved).
 *              Expanding outreach.send or auth.admin_login rows fires the
 *              audit-of-audit recorder (fire-and-forget).
 *  ANOMALIES — detection cards with dismiss/undo + "view in stream" jump.
 *
 * Visual system matches /admin/courses + /admin/agents (Fraunces titles,
 * Inter body, warm cream / dark forest palette, mini-chip pills).
 */

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, RefreshCw, Search } from "lucide-react";
import {
  useAdminAuditLog,
  useAuditAnomalies,
  useAuditPulse,
  useDismissAnomaly,
  useRecordAuditView,
  useUndismissAnomaly,
  type AdminAuditEntry,
  type AdminAuditFilters,
  type AnomalyDetection,
  type AuditPulseHourBucket,
  type AuditPulseResponse,
} from "@/lib/hooks/use-admin";
import { useAdminTheme } from "@/lib/hooks/use-admin-theme";

// ── Category palette ───────────────────────────────────────────────
type Category =
  | "course"
  | "coupon"
  | "bundle"
  | "feedback"
  | "outreach"
  | "auth"
  | "agent"
  | "exercise"
  | "lesson"
  | "mcq"
  | "other";

const CATEGORY_COLOR_LIGHT: Record<Category, { bg: string; fg: string; bar: string }> = {
  course:   { bg: "#d9efe5", fg: "#1f4f37", bar: "#1D9E75" },
  coupon:   { bg: "#ece1f7", fg: "#5a3da0", bar: "#7c5cc4" },
  bundle:   { bg: "#dfe9f7", fg: "#2a4f8a", bar: "#3a72c9" },
  feedback: { bg: "#f7e9cf", fg: "#8a5a17", bar: "#d6a54d" },
  outreach: { bg: "#f7d9d3", fg: "#a23f31", bar: "#d96252" },
  auth:     { bg: "#dceadf", fg: "#356d50", bar: "#8fd6b1" },
  agent:    { bg: "#e3deef", fg: "#3f348a", bar: "#7c5cc4" },
  exercise: { bg: "#e7f0d2", fg: "#4a6020", bar: "#a3c659" },
  lesson:   { bg: "#e7f0d2", fg: "#4a6020", bar: "#a3c659" },
  mcq:      { bg: "#e7f0d2", fg: "#4a6020", bar: "#a3c659" },
  other:    { bg: "#ece6da", fg: "#5a564b", bar: "#a39a85" },
};

// Dark mode: tone-tinted backgrounds (rgba of bar color) + lighter foreground.
const CATEGORY_COLOR_DARK: Record<Category, { bg: string; fg: string; bar: string }> = {
  course:   { bg: "rgba(29,158,117,0.18)",  fg: "#8fd6b1", bar: "#1D9E75" },
  coupon:   { bg: "rgba(124,92,196,0.20)",  fg: "#c5b3ec", bar: "#7c5cc4" },
  bundle:   { bg: "rgba(58,114,201,0.20)",  fg: "#a8c4ec", bar: "#3a72c9" },
  feedback: { bg: "rgba(214,165,77,0.18)",  fg: "#e9c682", bar: "#d6a54d" },
  outreach: { bg: "rgba(217,98,82,0.20)",   fg: "#eaa094", bar: "#d96252" },
  auth:     { bg: "rgba(143,214,177,0.18)", fg: "#a8e2c2", bar: "#8fd6b1" },
  agent:    { bg: "rgba(124,92,196,0.20)",  fg: "#c5b3ec", bar: "#7c5cc4" },
  exercise: { bg: "rgba(163,198,89,0.18)",  fg: "#cde29a", bar: "#a3c659" },
  lesson:   { bg: "rgba(163,198,89,0.18)",  fg: "#cde29a", bar: "#a3c659" },
  mcq:      { bg: "rgba(163,198,89,0.18)",  fg: "#cde29a", bar: "#a3c659" },
  other:    { bg: "rgba(163,154,133,0.18)", fg: "#bcb5a3", bar: "#a39a85" },
};

function categoryPalette(cat: Category, isDark: boolean) {
  return (isDark ? CATEGORY_COLOR_DARK : CATEGORY_COLOR_LIGHT)[cat];
}

function resolveCategory(raw: string): Category {
  return (raw as Category) in CATEGORY_COLOR_LIGHT ? (raw as Category) : "other";
}

function categoryOf(actionType: string): Category {
  const prefix = (actionType.split(".")[0] ?? "") as Category;
  if (prefix in CATEGORY_COLOR_LIGHT) return prefix;
  return "other";
}

const ACTION_GROUPS: { label: string; prefix: string }[] = [
  { label: "Course", prefix: "course" },
  { label: "Coupon", prefix: "coupon" },
  { label: "Bundle", prefix: "bundle" },
  { label: "Feedback", prefix: "feedback" },
  { label: "Outreach", prefix: "outreach" },
  { label: "Auth", prefix: "auth" },
];

// ── Time helpers ───────────────────────────────────────────────────
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  if (diff < 0) return "just now";
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

type WindowKey = "today" | "7d" | "30d" | "all";

function sinceForWindow(w: WindowKey): string | undefined {
  const now = new Date();
  if (w === "today") {
    const t = new Date(now);
    t.setHours(0, 0, 0, 0);
    return t.toISOString();
  }
  if (w === "7d") return new Date(now.getTime() - 7 * 86400_000).toISOString();
  if (w === "30d") return new Date(now.getTime() - 30 * 86400_000).toISOString();
  return undefined;
}

function diffKeys(
  before: Record<string, unknown> | null,
  after: Record<string, unknown> | null,
): string[] {
  const keys = new Set<string>();
  if (before) Object.keys(before).forEach((k) => keys.add(k));
  if (after) Object.keys(after).forEach((k) => keys.add(k));
  return Array.from(keys).filter((k) => {
    const a = before?.[k];
    const b = after?.[k];
    return JSON.stringify(a) !== JSON.stringify(b);
  });
}

function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

// ── Cross-tab message bus ──────────────────────────────────────────
// PULSE & ANOMALIES tabs send filter intents to STREAM via this state.
interface StreamIntent {
  since?: string;
  until?: string;
  actionType?: string;
  adminEmail?: string;
  scrollToId?: string;
  rowIds?: string[];
}

type TabKey = "pulse" | "stream" | "anomalies";

// ── Page ───────────────────────────────────────────────────────────
export default function AuditLogPage() {
  const { theme } = useAdminTheme();
  const isDark = theme === "dark";
  const [tab, setTab] = useState<TabKey>("pulse");
  const [streamIntent, setStreamIntent] = useState<StreamIntent>({});

  const pulseQ = useAuditPulse();
  const anomaliesQ = useAuditAnomalies();
  const openAnomalies = useMemo(
    () => (anomaliesQ.data?.items ?? []).filter((a) => !a.dismissed).length,
    [anomaliesQ.data],
  );

  function sendToStream(intent: StreamIntent) {
    setStreamIntent(intent);
    setTab("stream");
  }

  const TABS: { key: TabKey; label: string }[] = [
    { key: "pulse", label: "Pulse" },
    { key: "stream", label: "Stream" },
    { key: "anomalies", label: "Anomalies" },
  ];

  return (
    <div className="cf-audit-page" data-theme={theme}>
      <div className="cf-audit-shell">
        <header className="cf-audit-header">
          <div className="cf-audit-eyebrow">Administration · Audit</div>
          <h1 className="cf-audit-title">Admin audit log</h1>
          <p className="cf-audit-subtitle">
            Every privileged action recorded. Filter, expand, and investigate.
          </p>
        </header>

        <div
          role="tablist"
          aria-label="Audit cockpit tabs"
          className="cf-audit-tabbar"
        >
          {TABS.map((t) => {
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setTab(t.key)}
                className={`cf-audit-tab${active ? " cf-audit-tab-active" : ""}`}
              >
                {t.label}
                {t.key === "anomalies" && openAnomalies > 0 ? (
                  <span className="cf-audit-tab-dot" aria-hidden />
                ) : null}
              </button>
            );
          })}
        </div>

        {tab === "pulse" ? (
          <PulseTab
            data={pulseQ.data}
            isLoading={pulseQ.isLoading}
            isError={pulseQ.isError}
            error={pulseQ.error}
            openAnomalies={openAnomalies}
            anomalies={anomaliesQ.data?.items ?? []}
            onJumpToStream={sendToStream}
            onRefresh={() => {
              void pulseQ.refetch();
              void anomaliesQ.refetch();
            }}
            isFetching={pulseQ.isFetching || anomaliesQ.isFetching}
            isDark={isDark}
          />
        ) : null}

        {tab === "stream" ? (
          <StreamTab
            intent={streamIntent}
            clearIntent={() => setStreamIntent({})}
            isDark={isDark}
          />
        ) : null}

        {tab === "anomalies" ? (
          <AnomaliesTab
            items={anomaliesQ.data?.items ?? []}
            isLoading={anomaliesQ.isLoading}
            isError={anomaliesQ.isError}
            onJumpToStream={sendToStream}
            onRefresh={() => void anomaliesQ.refetch()}
            isFetching={anomaliesQ.isFetching}
          />
        ) : null}
      </div>

      <style>{buildStyles(isDark)}</style>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════
// PULSE TAB
// ════════════════════════════════════════════════════════════════════

function PulseTab({
  data,
  isLoading,
  isError,
  error,
  openAnomalies,
  anomalies,
  onJumpToStream,
  onRefresh,
  isFetching,
  isDark,
}: {
  data: AuditPulseResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  openAnomalies: number;
  anomalies: AnomalyDetection[];
  onJumpToStream: (i: StreamIntent) => void;
  onRefresh: () => void;
  isFetching: boolean;
  isDark: boolean;
}) {
  if (isLoading) {
    return <div className="cf-audit-empty">Loading pulse…</div>;
  }
  if (isError || !data) {
    return (
      <div className="cf-audit-empty cf-audit-error">
        Failed to load pulse: {(error as Error)?.message ?? "unknown"}
      </div>
    );
  }

  const { kpis } = data;
  const deltaPct =
    kpis.actions_yesterday > 0
      ? Math.round(
          ((kpis.actions_today - kpis.actions_yesterday) /
            kpis.actions_yesterday) *
            100,
        )
      : null;

  // Anomaly tile tone — red if any critical-and-open, amber if any
  // warn-and-open, otherwise neutral.
  const openCrit = anomalies.some((a) => !a.dismissed && a.severity === "critical");
  const openWarn = anomalies.some((a) => !a.dismissed && a.severity === "warn");
  const anomalyTone: "danger" | "warn" | "neutral" = openCrit
    ? "danger"
    : openWarn
      ? "warn"
      : "neutral";

  return (
    <div className="cf-audit-pulse">
      {/* refresh */}
      <div className="cf-audit-pulse-toolbar">
        <span className="cf-audit-pulse-stamp">
          Generated {relativeTime(data.generated_at)}
        </span>
        <button
          type="button"
          className="cf-audit-refresh"
          onClick={onRefresh}
          disabled={isFetching}
          aria-label="Refresh"
          title="Refresh"
        >
          <RefreshCw size={14} className={isFetching ? "cf-audit-spin" : undefined} />
        </button>
      </div>

      {/* Section A — KPI strip */}
      <div className="cf-kpi-strip">
        <KpiTile
          label="Today"
          value={String(kpis.actions_today)}
          sub={
            <span>
              yesterday: {kpis.actions_yesterday}
              {deltaPct != null ? (
                <span
                  className={`cf-kpi-delta cf-kpi-delta-${deltaPct >= 0 ? "up" : "down"}`}
                >
                  {deltaPct >= 0 ? "▲" : "▼"} {Math.abs(deltaPct)}%
                </span>
              ) : null}
            </span>
          }
        />
        <KpiTile
          label="Active admins"
          value={String(kpis.distinct_admins_today)}
          sub="distinct today"
        />
        <KpiTile
          label="Pace (last hour)"
          value={`${kpis.actions_per_hour_recent.toFixed(1)}/h`}
          sub={`baseline: ${kpis.actions_per_hour_baseline.toFixed(1)}/h`}
        />
        <KpiTile
          label="Anomalies open"
          value={String(openAnomalies || kpis.anomaly_count_today)}
          sub={openCrit ? "critical detected" : openWarn ? "needs review" : "all clear"}
          tone={anomalyTone}
        />
      </div>

      {/* Section B — Hourly activity */}
      <Section title="Last 24 hours · UTC">
        <HourlyBars
          buckets={data.hourly_sparkline}
          isDark={isDark}
          onClickHour={(b) => {
            const start = new Date(b.hour_iso);
            const end = new Date(start.getTime() + 3600_000);
            onJumpToStream({
              since: start.toISOString(),
              until: end.toISOString(),
            });
          }}
        />
      </Section>

      {/* Section C — Categories */}
      <Section title="Categories · 7 days">
        <CategoryBars
          rows={data.categories}
          isDark={isDark}
          onClickCategory={(c) => onJumpToStream({ actionType: c })}
        />
      </Section>

      {/* Section D + E side-by-side */}
      <div className="cf-pulse-grid-2">
        <Section title="Top actors · 7 days">
          <TopActors
            actors={data.top_actors}
            onClickActor={(email) => onJumpToStream({ adminEmail: email })}
          />
        </Section>

        <Section title="Top resources · 7 days">
          <TopResources
            courses={data.top_courses}
            students={data.top_students}
            agents={data.top_agents}
          />
        </Section>
      </div>

      {/* Section F — Hot critical */}
      <Section title="Hot critical · last 10 critical actions">
        <HotCritical
          rows={data.hot_critical}
          isDark={isDark}
          onClickRow={(id) => onJumpToStream({ scrollToId: id })}
        />
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="cf-pulse-section">
      <div className="cf-pulse-section-title">{title}</div>
      {children}
    </section>
  );
}

function KpiTile({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub: React.ReactNode;
  tone?: "danger" | "warn" | "neutral";
}) {
  return (
    <div className={`cf-kpi-tile cf-kpi-tone-${tone}`}>
      <div className="cf-kpi-label">{label}</div>
      <div className="cf-kpi-value">{value}</div>
      <div className="cf-kpi-sub">{sub}</div>
    </div>
  );
}

// ── Hourly stacked bar SVG ────────────────────────────────────────
function HourlyBars({
  buckets,
  onClickHour,
  isDark,
}: {
  buckets: AuditPulseHourBucket[];
  onClickHour: (b: AuditPulseHourBucket) => void;
  isDark: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);

  const max = useMemo(
    () => Math.max(1, ...buckets.map((b) => b.count_total)),
    [buckets],
  );

  if (buckets.length === 0) {
    return <div className="cf-pulse-empty">No activity in the last 24h.</div>;
  }

  const W = 800;
  const H = 140;
  const padX = 8;
  const padY = 16;
  const usableW = W - padX * 2;
  const usableH = H - padY * 2;
  const slotW = usableW / buckets.length;
  const barW = slotW * 0.72;

  return (
    <div className="cf-pulse-hourly">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="cf-pulse-hourly-svg"
        role="img"
        aria-label="Hourly audit activity over last 24h"
      >
        {buckets.map((b, i) => {
          const x = padX + i * slotW + (slotW - barW) / 2;
          const totalH = (b.count_total / max) * usableH;
          let stackY = padY + usableH;
          const segs = Object.entries(b.count_by_category).filter(
            ([, c]) => c > 0,
          );
          return (
            <g
              key={b.hour_iso}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover((v) => (v === i ? null : v))}
              onClick={() => onClickHour(b)}
              style={{ cursor: "pointer" }}
            >
              {/* invisible hit rect spans full slot */}
              <rect
                x={padX + i * slotW}
                y={padY}
                width={slotW}
                height={usableH}
                fill="transparent"
              />
              {segs.map(([cat, count]) => {
                const segH = (count / b.count_total) * totalH;
                stackY -= segH;
                const palette = categoryPalette(resolveCategory(cat), isDark);
                return (
                  <rect
                    key={cat}
                    x={x}
                    y={stackY}
                    width={barW}
                    height={Math.max(0.5, segH)}
                    fill={palette.bar}
                    opacity={hover === i ? 1 : 0.85}
                  />
                );
              })}
              {/* hover ring */}
              {hover === i ? (
                <rect
                  x={x - 1}
                  y={padY + usableH - totalH - 1}
                  width={barW + 2}
                  height={totalH + 2}
                  fill="none"
                  stroke={isDark ? "#8fd6b1" : "#2c3830"}
                  strokeWidth={1}
                />
              ) : null}
            </g>
          );
        })}
      </svg>

      {hover != null ? (
        <HourTooltip bucket={buckets[hover]!} isDark={isDark} />
      ) : (
        <div className="cf-pulse-hourly-legend">
          {Object.entries(CATEGORY_COLOR_LIGHT)
            .filter(([k]) => k !== "other")
            .slice(0, 8)
            .map(([k, v]) => (
              <span key={k} className="cf-pulse-legend-chip">
                <span
                  className="cf-pulse-legend-swatch"
                  style={{ background: v.bar }}
                />
                {k}
              </span>
            ))}
        </div>
      )}
    </div>
  );
}

function HourTooltip({ bucket, isDark }: { bucket: AuditPulseHourBucket; isDark: boolean }) {
  const d = new Date(bucket.hour_iso);
  const label = d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  const entries = Object.entries(bucket.count_by_category)
    .filter(([, c]) => c > 0)
    .sort((a, b) => b[1] - a[1]);
  return (
    <div className="cf-pulse-tooltip">
      <div className="cf-pulse-tooltip-head">
        {label} · <strong>{bucket.count_total}</strong> actions
      </div>
      <div className="cf-pulse-tooltip-list">
        {entries.map(([cat, count]) => {
          const palette = categoryPalette(resolveCategory(cat), isDark);
          return (
            <span key={cat} className="cf-pulse-tooltip-row">
              <span
                className="cf-pulse-legend-swatch"
                style={{ background: palette.bar }}
              />
              {cat} <strong>{count}</strong>
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ── Category bars ─────────────────────────────────────────────────
function CategoryBars({
  rows,
  onClickCategory,
  isDark,
}: {
  rows: AuditPulseResponse["categories"];
  onClickCategory: (cat: string) => void;
  isDark: boolean;
}) {
  const sorted = useMemo(
    () => [...rows].sort((a, b) => b.count_7d - a.count_7d),
    [rows],
  );
  const max = Math.max(1, ...sorted.map((r) => r.count_7d));
  if (sorted.length === 0) {
    return <div className="cf-pulse-empty">No category data yet.</div>;
  }
  return (
    <ul className="cf-pulse-catbars">
      {sorted.map((r) => {
        const palette = categoryPalette(resolveCategory(r.category), isDark);
        const pct = (r.count_7d / max) * 100;
        return (
          <li key={r.category}>
            <button
              type="button"
              className="cf-pulse-catbar-row"
              onClick={() => onClickCategory(r.category)}
            >
              <span
                className="cf-mini-chip"
                style={{ background: palette.bg, color: palette.fg }}
              >
                {r.category}
              </span>
              <span className="cf-pulse-catbar-track">
                <span
                  className="cf-pulse-catbar-fill"
                  style={{ width: `${pct}%`, background: palette.bar }}
                />
              </span>
              <span className="cf-pulse-catbar-counts">
                <strong>{r.count_today}</strong>
                <span className="cf-pulse-catbar-slash">/</span>
                {r.count_7d}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

// ── Top actors / resources / hot critical ─────────────────────────
function TopActors({
  actors,
  onClickActor,
}: {
  actors: AuditPulseResponse["top_actors"];
  onClickActor: (email: string) => void;
}) {
  if (actors.length === 0) {
    return <div className="cf-pulse-empty">No actors yet.</div>;
  }
  return (
    <ul className="cf-pulse-list">
      {actors.map((a) => (
        <li key={a.admin_id ?? a.admin_email}>
          <button
            type="button"
            className="cf-pulse-list-row"
            onClick={() => onClickActor(a.admin_email)}
          >
            <span className="cf-pulse-list-primary">{a.admin_email}</span>
            <span className="cf-pulse-chip">{a.count_7d}</span>
            <span className="cf-pulse-list-time">
              {relativeTime(a.last_action_at)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function TopResources({
  courses,
  students,
  agents,
}: {
  courses: AuditPulseResponse["top_courses"];
  students: AuditPulseResponse["top_students"];
  agents: AuditPulseResponse["top_agents"];
}) {
  return (
    <div className="cf-pulse-resgrid">
      <ResourceCard title="Courses" rows={courses} kind="course" />
      <ResourceCard title="Students" rows={students} kind="student" />
      <ResourceCard title="Agents" rows={agents} kind="agent" />
    </div>
  );
}

function ResourceCard({
  title,
  rows,
  kind,
}: {
  title: string;
  rows: AuditPulseResponse["top_courses"];
  kind: "course" | "student" | "agent";
}) {
  return (
    <div className="cf-pulse-rescard">
      <div className="cf-pulse-rescard-title">{title}</div>
      {rows.length === 0 ? (
        <div className="cf-pulse-empty cf-pulse-empty-small">No data.</div>
      ) : (
        <ul className="cf-pulse-list">
          {rows.map((r) => {
            const label = r.resource_label ?? r.resource_id;
            const inner = (
              <>
                <span className="cf-pulse-list-primary">{label}</span>
                <span className="cf-pulse-chip">{r.count_7d}</span>
              </>
            );
            if (kind === "course") {
              return (
                <li key={r.resource_id}>
                  <Link
                    href={`/admin/courses/${r.resource_id}/edit`}
                    className="cf-pulse-list-row cf-pulse-list-row-link"
                  >
                    {inner}
                  </Link>
                </li>
              );
            }
            if (kind === "agent") {
              return (
                <li key={r.resource_id}>
                  <Link
                    href={`/admin/agents?agent=${encodeURIComponent(r.resource_id)}`}
                    className="cf-pulse-list-row cf-pulse-list-row-link"
                  >
                    {inner}
                  </Link>
                </li>
              );
            }
            return (
              <li key={r.resource_id}>
                <div className="cf-pulse-list-row cf-pulse-list-row-static">
                  {inner}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

const SEV_COLOR: Record<"critical" | "warn" | "info", string> = {
  critical: "#d96252",
  warn: "#d6a54d",
  info: "#3a72c9",
};

function HotCritical({
  rows,
  onClickRow,
  isDark,
}: {
  rows: AuditPulseResponse["hot_critical"];
  onClickRow: (id: string) => void;
  isDark: boolean;
}) {
  if (rows.length === 0) {
    return <div className="cf-pulse-empty">No critical actions recently.</div>;
  }
  return (
    <ul className="cf-pulse-list">
      {rows.map((r) => {
        const cat = categoryOf(r.action_type);
        const palette = categoryPalette(cat, isDark);
        return (
          <li key={r.id}>
            <button
              type="button"
              className="cf-pulse-hot-row"
              onClick={() => onClickRow(r.id)}
            >
              <span
                className="cf-pulse-hot-dot"
                style={{ background: SEV_COLOR[r.severity] }}
                aria-hidden
              />
              <span
                className="cf-mini-chip"
                style={{ background: palette.bg, color: palette.fg }}
              >
                {r.action_type}
              </span>
              <span className="cf-pulse-hot-admin">{r.admin_email}</span>
              <span className="cf-pulse-hot-summary">{r.summary}</span>
              <span className="cf-pulse-list-time">
                {relativeTime(r.created_at)}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

// ════════════════════════════════════════════════════════════════════
// STREAM TAB (preserves original behavior, adds audit-of-audit firing)
// ════════════════════════════════════════════════════════════════════

function StreamTab({
  intent,
  clearIntent,
  isDark,
}: {
  intent: StreamIntent;
  clearIntent: () => void;
  isDark: boolean;
}) {
  const [search, setSearch] = useState("");
  const [actionType, setActionType] = useState<string>("");
  const [adminEmail, setAdminEmail] = useState<string>("");
  const [windowKey, setWindowKey] = useState<WindowKey>("7d");
  const [overrideSince, setOverrideSince] = useState<string | undefined>(undefined);
  const [overrideUntil, setOverrideUntil] = useState<string | undefined>(undefined);
  const [scrollToId, setScrollToId] = useState<string | null>(null);
  const [rowIdFilter, setRowIdFilter] = useState<string[] | null>(null);

  // Apply incoming intent from PULSE / ANOMALIES tab once.
  const appliedRef = useRef<StreamIntent | null>(null);
  useEffect(() => {
    if (appliedRef.current === intent) return;
    appliedRef.current = intent;
    if (intent.actionType) setActionType(intent.actionType);
    if (intent.adminEmail) setAdminEmail(intent.adminEmail);
    if (intent.since) {
      setOverrideSince(intent.since);
      setWindowKey("all");
    }
    if (intent.until) setOverrideUntil(intent.until);
    if (!intent.since && !intent.until) {
      setOverrideSince(undefined);
      setOverrideUntil(undefined);
    }
    if (intent.scrollToId) setScrollToId(intent.scrollToId);
    setRowIdFilter(intent.rowIds && intent.rowIds.length > 0 ? intent.rowIds : null);
  }, [intent]);

  const filters: AdminAuditFilters = useMemo(() => {
    const f: AdminAuditFilters = {};
    if (actionType) f.action_type = actionType;
    if (overrideSince) {
      f.since = overrideSince;
    } else {
      const since = sinceForWindow(windowKey);
      if (since) f.since = since;
    }
    if (overrideUntil) f.until = overrideUntil;
    return f;
  }, [actionType, windowKey, overrideSince, overrideUntil]);

  const { data, isLoading, isError, error, refetch, isFetching } =
    useAdminAuditLog(filters);
  const entries = data ?? [];

  const adminOptions = useMemo(() => {
    const s = new Set<string>();
    entries.forEach((e) => e.admin_email && s.add(e.admin_email));
    return Array.from(s).sort();
  }, [entries]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return entries.filter((e) => {
      if (adminEmail && e.admin_email !== adminEmail) return false;
      if (rowIdFilter && !rowIdFilter.includes(e.id)) return false;
      if (!q) return true;
      return (
        e.admin_email.toLowerCase().includes(q) ||
        e.action_type.toLowerCase().includes(q) ||
        (e.resource_id ?? "").toLowerCase().includes(q) ||
        (e.summary ?? "").toLowerCase().includes(q)
      );
    });
  }, [entries, search, adminEmail, rowIdFilter]);

  // Scroll the requested row into view + flash highlight once data is in.
  useEffect(() => {
    if (!scrollToId) return;
    const el = document.querySelector<HTMLElement>(
      `[data-audit-row="${scrollToId}"]`,
    );
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("cf-audit-flash");
      const t = setTimeout(() => el.classList.remove("cf-audit-flash"), 1800);
      setScrollToId(null);
      return () => clearTimeout(t);
    }
  }, [scrollToId, visible]);

  const WINDOWS: { key: WindowKey; label: string }[] = [
    { key: "today", label: "Today" },
    { key: "7d", label: "7d" },
    { key: "30d", label: "30d" },
    { key: "all", label: "All" },
  ];

  const filterActive =
    overrideSince || overrideUntil || rowIdFilter || adminEmail || actionType;

  return (
    <>
      <div className="cf-audit-filterbar">
        <div className="cf-audit-search">
          <Search size={14} aria-hidden />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search admin, action, resource id…"
            aria-label="Search audit entries"
          />
        </div>

        <select
          className="cf-audit-select"
          value={actionType}
          onChange={(e) => setActionType(e.target.value)}
          aria-label="Filter by action type"
        >
          <option value="">All actions</option>
          {ACTION_GROUPS.map((g) => (
            <optgroup key={g.prefix} label={g.label}>
              <option value={`${g.prefix}.create`}>{g.prefix}.create</option>
              <option value={`${g.prefix}.update`}>{g.prefix}.update</option>
              <option value={`${g.prefix}.delete`}>{g.prefix}.delete</option>
            </optgroup>
          ))}
        </select>

        <select
          className="cf-audit-select"
          value={adminEmail}
          onChange={(e) => setAdminEmail(e.target.value)}
          aria-label="Filter by admin"
          disabled={adminOptions.length === 0}
        >
          <option value="">All admins</option>
          {adminOptions.map((email) => (
            <option key={email} value={email}>
              {email}
            </option>
          ))}
        </select>

        <div className="cf-audit-pills" role="group" aria-label="Time window">
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              type="button"
              className={`cf-audit-pill${windowKey === w.key && !overrideSince ? " cf-audit-pill-active" : ""}`}
              onClick={() => {
                setWindowKey(w.key);
                setOverrideSince(undefined);
                setOverrideUntil(undefined);
              }}
            >
              {w.label}
            </button>
          ))}
        </div>

        {filterActive ? (
          <button
            type="button"
            className="cf-audit-clear"
            onClick={() => {
              setActionType("");
              setAdminEmail("");
              setOverrideSince(undefined);
              setOverrideUntil(undefined);
              setRowIdFilter(null);
              clearIntent();
            }}
          >
            Clear filters
          </button>
        ) : null}

        <button
          type="button"
          className="cf-audit-refresh"
          onClick={() => refetch()}
          disabled={isFetching}
          aria-label="Refresh"
          title="Refresh"
        >
          <RefreshCw size={14} className={isFetching ? "cf-audit-spin" : undefined} />
        </button>
      </div>

      {(overrideSince || rowIdFilter) ? (
        <div className="cf-audit-pinbanner">
          {overrideSince ? (
            <>
              Pinned to{" "}
              <strong>
                {new Date(overrideSince).toLocaleString()}
                {overrideUntil
                  ? ` → ${new Date(overrideUntil).toLocaleString()}`
                  : ""}
              </strong>
            </>
          ) : null}
          {rowIdFilter ? (
            <>
              Showing {rowIdFilter.length} flagged row
              {rowIdFilter.length === 1 ? "" : "s"} from anomaly
            </>
          ) : null}
        </div>
      ) : null}

      {isLoading ? (
        <div className="cf-audit-empty">Loading audit entries…</div>
      ) : isError ? (
        <div className="cf-audit-empty cf-audit-error">
          Failed to load audit log: {(error as Error)?.message ?? "unknown"}
        </div>
      ) : visible.length === 0 ? (
        <div className="cf-audit-empty">No audit entries match these filters.</div>
      ) : (
        <ul className="cf-audit-list">
          {visible.map((entry) => (
            <AuditCard
              key={`${entry.source}:${entry.id}`}
              entry={entry}
              isDark={isDark}
            />
          ))}
        </ul>
      )}

      {entries.length >= 200 ? (
        <p className="cf-audit-footer">
          Showing the latest 200 entries. Narrow filters or pick a smaller window to see more.
        </p>
      ) : null}
    </>
  );
}

function AuditCard({ entry, isDark }: { entry: AdminAuditEntry; isDark: boolean }) {
  const [open, setOpen] = useState(false);
  const recordView = useRecordAuditView();
  const cat = categoryOf(entry.action_type);
  const color = categoryPalette(cat, isDark);
  const resourceShort =
    entry.resource_id && entry.resource_id.length > 8
      ? entry.resource_id.slice(0, 8)
      : entry.resource_id;
  const resourcePill =
    entry.resource_type && resourceShort
      ? `${entry.resource_type}/${resourceShort}`
      : entry.resource_type;

  const changed = useMemo(
    () => diffKeys(entry.before, entry.after),
    [entry.before, entry.after],
  );
  const hasDiff = changed.length > 0;
  const extraKeys = entry.extra ? Object.keys(entry.extra) : [];
  const canExpand = hasDiff || extraKeys.length > 0;

  function handleToggle() {
    if (!canExpand) return;
    const next = !open;
    setOpen(next);
    // Audit-of-audit: fire-and-forget when a sensitive row is expanded.
    if (next) {
      if (entry.action_type === "outreach.send") {
        recordView.mutate({
          audit_row_id: entry.id,
          viewed_field: "outreach_body",
        });
      } else if (entry.action_type === "auth.admin_login") {
        recordView.mutate({
          audit_row_id: entry.id,
          viewed_field: "auth_ip",
        });
      }
    }
  }

  return (
    <li className="cf-audit-card" data-audit-row={entry.id}>
      <button
        type="button"
        className="cf-audit-card-head"
        onClick={handleToggle}
        aria-expanded={open}
        aria-disabled={!canExpand}
      >
        <div className="cf-audit-card-row1">
          <span
            className="cf-audit-action-pill"
            style={{ background: color.bg, color: color.fg }}
          >
            {entry.action_type}
          </span>
          {resourcePill ? (
            <span className="cf-audit-resource-pill">{resourcePill}</span>
          ) : null}
          <span
            className="cf-audit-time"
            title={new Date(entry.created_at).toLocaleString()}
          >
            {relativeTime(entry.created_at)}
          </span>
          <span className="cf-audit-source">{entry.source}</span>
          {canExpand ? (
            <ChevronDown
              size={14}
              className={`cf-audit-chevron${open ? " cf-audit-chevron-open" : ""}`}
              aria-hidden
            />
          ) : null}
        </div>
        <div className="cf-audit-card-row2">
          <span className="cf-audit-admin">{entry.admin_email}</span>
          <span className="cf-audit-summary">{entry.summary}</span>
        </div>
      </button>

      {open && canExpand ? (
        <div className="cf-audit-card-body">
          {entry.action_type === "outreach.send" && entry.extra ? (
            <OutreachPreview extra={entry.extra} />
          ) : null}
          {entry.action_type === "auth.admin_login" && entry.extra ? (
            <AuthLoginContext extra={entry.extra} />
          ) : null}

          {hasDiff ? (
            <div className="cf-audit-diff">
              <div className="cf-audit-diff-header">Changes</div>
              <div className="cf-audit-diff-grid">
                <div className="cf-audit-diff-col-header">Before</div>
                <div className="cf-audit-diff-col-header">After</div>
                {changed.map((k) => (
                  <DiffRow
                    key={k}
                    fieldKey={k}
                    before={entry.before?.[k]}
                    after={entry.after?.[k]}
                  />
                ))}
              </div>
            </div>
          ) : null}

          {entry.extra && extraKeys.length > 0 ? (
            <div className="cf-audit-extra">
              <div className="cf-audit-diff-header">Metadata</div>
              <dl className="cf-audit-kv">
                {extraKeys.map((k) => (
                  <div key={k} className="cf-audit-kv-row">
                    <dt>{k}</dt>
                    <dd>{fmtValue(entry.extra?.[k])}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function DiffRow({
  fieldKey,
  before,
  after,
}: {
  fieldKey: string;
  before: unknown;
  after: unknown;
}) {
  return (
    <>
      <div className="cf-audit-diff-cell cf-audit-diff-before">
        <span className="cf-audit-diff-key">{fieldKey}</span>
        <span className="cf-audit-diff-val">{fmtValue(before)}</span>
      </div>
      <div className="cf-audit-diff-cell cf-audit-diff-after">
        <span className="cf-audit-diff-key">{fieldKey}</span>
        <span className="cf-audit-diff-val">{fmtValue(after)}</span>
      </div>
    </>
  );
}

function OutreachPreview({ extra }: { extra: Record<string, unknown> }) {
  const channel = extra.channel ? String(extra.channel) : null;
  const preview = extra.text_preview ? String(extra.text_preview) : null;
  if (!preview && !channel) return null;
  return (
    <div className="cf-audit-outreach">
      {channel ? <span className="cf-audit-channel-badge">{channel}</span> : null}
      {preview ? (
        <blockquote className="cf-audit-outreach-quote">{preview}</blockquote>
      ) : null}
    </div>
  );
}

function AuthLoginContext({ extra }: { extra: Record<string, unknown> }) {
  const ip = extra.ip ? String(extra.ip) : null;
  const ua = extra.user_agent ? String(extra.user_agent) : null;
  if (!ip && !ua) return null;
  return (
    <div className="cf-audit-login">
      {ip ? (
        <div>
          <span className="cf-audit-login-label">IP</span>
          <span className="cf-audit-login-val">{ip}</span>
        </div>
      ) : null}
      {ua ? (
        <div>
          <span className="cf-audit-login-label">User-Agent</span>
          <span className="cf-audit-login-val">{ua}</span>
        </div>
      ) : null}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════
// ANOMALIES TAB
// ════════════════════════════════════════════════════════════════════

function AnomaliesTab({
  items,
  isLoading,
  isError,
  onJumpToStream,
  onRefresh,
  isFetching,
}: {
  items: AnomalyDetection[];
  isLoading: boolean;
  isError: boolean;
  onJumpToStream: (i: StreamIntent) => void;
  onRefresh: () => void;
  isFetching: boolean;
}) {
  const [showDismissed, setShowDismissed] = useState(false);

  const open = items.filter((a) => !a.dismissed);
  const dismissed = items.filter((a) => a.dismissed);
  const visible = showDismissed ? items : open;

  return (
    <>
      <div className="cf-anom-toolbar">
        <div className="cf-anom-toolbar-head">
          <div className="cf-pulse-section-title cf-anom-title">
            Detected anomalies · last 24h
          </div>
          <div className="cf-anom-counts">
            <strong>{open.length}</strong> open · {dismissed.length} dismissed
          </div>
        </div>
        <label className="cf-anom-toggle">
          <input
            type="checkbox"
            checked={showDismissed}
            onChange={(e) => setShowDismissed(e.target.checked)}
          />
          Show dismissed
        </label>
        <button
          type="button"
          className="cf-audit-refresh"
          onClick={onRefresh}
          disabled={isFetching}
          aria-label="Refresh"
          title="Refresh"
        >
          <RefreshCw size={14} className={isFetching ? "cf-audit-spin" : undefined} />
        </button>
      </div>

      {isLoading ? (
        <div className="cf-audit-empty">Loading anomalies…</div>
      ) : isError ? (
        <div className="cf-audit-empty cf-audit-error">
          Failed to load anomalies.
        </div>
      ) : visible.length === 0 ? (
        <div className="cf-audit-empty">
          {showDismissed ? "No anomalies." : "No open anomalies. All clear."}
        </div>
      ) : (
        <ul className="cf-anom-list">
          {visible.map((a) => (
            <AnomalyCard
              key={a.fingerprint}
              anomaly={a}
              onJumpToStream={onJumpToStream}
            />
          ))}
        </ul>
      )}
    </>
  );
}

function AnomalyCard({
  anomaly,
  onJumpToStream,
}: {
  anomaly: AnomalyDetection;
  onJumpToStream: (i: StreamIntent) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const dismiss = useDismissAnomaly();
  const undismiss = useUndismissAnomaly();
  const tone = SEV_COLOR[anomaly.severity];

  function handleDismiss() {
    const note = window.prompt(
      "Optional note (why are you dismissing this?)",
      "",
    );
    if (note === null) return; // user cancelled
    dismiss.mutate({
      fingerprint: anomaly.fingerprint,
      note: note.trim() || undefined,
    });
  }

  function handleUndismiss() {
    undismiss.mutate({ fingerprint: anomaly.fingerprint });
  }

  return (
    <li className="cf-anom-card" style={{ borderLeftColor: tone }}>
      <div className="cf-anom-row1">
        <span className="cf-mini-chip cf-anom-rule">
          {anomaly.rule_type.replace(/_/g, " ")}
        </span>
        <span
          className="cf-anom-sev"
          style={{ background: tone, color: "#fff" }}
        >
          {anomaly.severity}
        </span>
        {anomaly.dismissed ? (
          <span className="cf-anom-dismissed-pill">Dismissed</span>
        ) : null}
        <span className="cf-pulse-list-time cf-anom-time">
          {relativeTime(anomaly.detected_at)}
        </span>
      </div>

      <div className="cf-anom-row2">
        <span className="cf-anom-admin">{anomaly.admin_email}</span>
        <span
          className={`cf-anom-desc${anomaly.dismissed ? " cf-anom-desc-dismissed" : ""}`}
        >
          {anomaly.description}
        </span>
      </div>

      <div className="cf-anom-row3">
        <button
          type="button"
          className="cf-anom-toggle-btn"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Hide details" : "Show details"}
        </button>
        {anomaly.dismissed ? (
          <button
            type="button"
            className="cf-anom-btn cf-anom-btn-undo"
            onClick={handleUndismiss}
            disabled={undismiss.isPending}
          >
            Undo dismiss
          </button>
        ) : (
          <button
            type="button"
            className="cf-anom-btn cf-anom-btn-dismiss"
            onClick={handleDismiss}
            disabled={dismiss.isPending}
          >
            Dismiss
          </button>
        )}
      </div>

      {expanded ? (
        <div className="cf-anom-detail">
          <div className="cf-anom-detail-row">
            <span className="cf-anom-detail-label">Window</span>
            <span className="cf-anom-detail-val">
              {new Date(anomaly.window_start).toLocaleString()} →{" "}
              {new Date(anomaly.window_end).toLocaleString()}
            </span>
          </div>
          <div className="cf-anom-detail-row">
            <span className="cf-anom-detail-label">Audit rows</span>
            <span className="cf-anom-detail-val">
              {anomaly.audit_row_ids.length} matching row
              {anomaly.audit_row_ids.length === 1 ? "" : "s"}
            </span>
          </div>
          {anomaly.audit_row_ids.length > 0 ? (
            <button
              type="button"
              className="cf-anom-btn cf-anom-btn-view"
              onClick={() =>
                onJumpToStream({
                  rowIds: anomaly.audit_row_ids,
                  since: anomaly.window_start,
                  until: anomaly.window_end,
                })
              }
            >
              View in stream
            </button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

// ════════════════════════════════════════════════════════════════════
// Styles
// ════════════════════════════════════════════════════════════════════
function buildStyles(isDark: boolean): string {
  // Palette tokens — mirror /admin/agents + /admin/courses for consistency.
  const ink         = isDark ? "#f0ece1" : "#10120e";
  const inkSoft     = isDark ? "#e2dccc" : "#1a2620";
  const muted       = isDark ? "#9a9588" : "#686559";
  const muted2      = isDark ? "#7a7568" : "#8f897d";
  const mutedSoft   = isDark ? "#bcb5a3" : "#7a7565";
  const line        = isDark ? "#2c3830" : "#dbd1bf";
  const lineSoft    = isDark ? "#26302a" : "#e7decd";
  const lineSoft2   = isDark ? "#1f2823" : "#efe7d4";
  const eyebrow     = isDark ? "#8fd6b1" : "#356d50";
  const eyebrowDot  = isDark ? "#8fd6b1" : "#4e9470";
  const cardBg      = isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.92)";
  const cardBgSoft  = isDark ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.7)";
  const panelBg     = isDark ? "rgba(15,22,18,0.85)" : "rgba(255,252,245,0.85)";
  const searchBg    = isDark ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.85)";
  const pageBg      = isDark
    ? "radial-gradient(ellipse 120% 80% at 20% 0%, #0f1612, #0a110d 55%, #060d0a 100%)"
    : "radial-gradient(ellipse 120% 80% at 20% 0%, #fdfaf3, #f7f3ea 55%, #efe9d9 100%)";
  const tabBarBg    = isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.7)";
  const tabHover    = isDark ? "rgba(143,214,177,0.10)" : "rgba(29,158,117,0.08)";
  const pillActiveBg = isDark ? "#8fd6b1" : "#1f4f37";
  const pillActiveFg = isDark ? "#0a110d" : "#fdfaf3";
  const accent      = "#1D9E75";
  const accentFg    = "#ffffff";
  const danger      = isDark ? "#eaa094" : "#a23f31";
  const dangerBg    = isDark ? "rgba(217,98,82,0.18)" : "#f7d9d3";
  const dangerSoft  = isDark ? "rgba(217,98,82,0.10)" : "rgba(217,98,82,0.06)";
  const dangerBorder = isDark ? "rgba(217,98,82,0.32)" : "rgba(217,98,82,0.32)";
  const okSoft      = isDark ? "rgba(78,148,112,0.12)" : "rgba(78,148,112,0.08)";
  const okBorder    = isDark ? "rgba(143,214,177,0.28)" : "rgba(78,148,112,0.22)";
  const okText      = isDark ? "#8fd6b1" : "#1f4f37";
  const warnSoft    = isDark ? "rgba(214,165,77,0.12)" : "rgba(214,165,77,0.06)";
  const warnBorder  = isDark ? "rgba(214,165,77,0.32)" : "rgba(214,165,77,0.32)";
  const diffBg      = isDark ? "rgba(255,255,255,0.02)" : "rgba(247,243,234,0.6)";
  const flashBg     = isDark ? "rgba(143,214,177,0.18)" : "rgba(143,214,177,0.35)";
  const tooltipBg   = isDark ? "#1a2620" : "#2c3830";
  const tooltipFg   = "#fdfaf3";
  const hourBg      = isDark ? "rgba(255,255,255,0.03)" : "rgba(247,243,234,0.5)";
  const rowHover    = isDark ? "rgba(143,214,177,0.08)" : "rgba(29,158,117,0.06)";
  const trackBg     = isDark ? "rgba(255,255,255,0.08)" : "rgba(26,38,32,0.06)";
  const resourceBg  = isDark ? "rgba(255,255,255,0.06)" : "rgba(26,38,32,0.06)";
  const resourceFg  = isDark ? "#bcb5a3" : "#3a3a3a";
  const summaryFg   = isDark ? "#c4beae" : "#3a3a3a";
  const arrowColor  = isDark ? "%23bcb5a3" : "%237a7565";
  const selectArrow = `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='${arrowColor}' stroke-width='2'><polyline points='6 9 12 15 18 9'/></svg>")`;
  const pinBg       = isDark ? "rgba(143,214,177,0.10)" : "rgba(78,148,112,0.08)";
  const pinBorder   = isDark ? "rgba(143,214,177,0.28)" : "rgba(78,148,112,0.22)";
  const btnViewBg   = isDark ? "#8fd6b1" : "#1f4f37";
  const btnViewFg   = isDark ? "#0a110d" : "#fdfaf3";
  const btnViewHover = isDark ? "#a8e2c2" : "#163b29";
  const outreachBg  = isDark ? "rgba(217,98,82,0.10)" : "rgba(217,98,82,0.05)";
  const outreachBorder = isDark ? "rgba(217,98,82,0.28)" : "rgba(217,98,82,0.18)";
  const outreachQuoteBg = isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.7)";
  const refreshHover = isDark ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,1)";
  const dismissedPillBg = isDark ? "rgba(255,255,255,0.06)" : "rgba(26,38,32,0.08)";
  const dismissedPillFg = isDark ? "#9a9588" : "#5a564b";

  return `
  .cf-audit-page {
    min-height: 100vh;
    background: ${pageBg};
    color: ${inkSoft};
    font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
  }
  .cf-audit-shell {
    max-width: 1400px;
    margin: 0 auto;
    padding: 32px 28px 64px;
  }
  .cf-audit-header { margin-bottom: 18px; }
  .cf-audit-eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 10px;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    font-weight: 700;
    color: ${eyebrow};
    margin-bottom: 10px;
  }
  .cf-audit-eyebrow::before {
    content: "";
    width: 6px; height: 6px;
    border-radius: 50%;
    background: ${eyebrowDot};
    box-shadow: 0 0 0 4px rgba(78,148,112,0.18);
  }
  .cf-audit-title {
    font-family: var(--font-fraunces), Georgia, serif;
    font-size: 24px;
    font-weight: 600;
    letter-spacing: -0.02em;
    margin: 0;
    color: ${ink};
  }
  .cf-audit-subtitle {
    margin: 4px 0 0;
    font-size: 13px;
    color: ${muted};
    line-height: 1.5;
  }

  /* Tab bar */
  .cf-audit-tabbar {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px;
    border-radius: 999px;
    background: ${tabBarBg};
    border: 1px solid ${line};
    margin: 18px 0 20px;
  }
  .cf-audit-tab {
    position: relative;
    appearance: none;
    border: none;
    background: transparent;
    padding: 7px 18px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: ${inkSoft};
    cursor: pointer;
    transition: background .15s, color .15s;
  }
  .cf-audit-tab:hover { background: ${tabHover}; }
  .cf-audit-tab-active {
    background: ${accent};
    color: ${accentFg};
  }
  .cf-audit-tab-active:hover { background: ${accent}; }
  .cf-audit-tab-dot {
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    background: #d96252;
    margin-left: 6px;
    vertical-align: middle;
    box-shadow: 0 0 0 3px rgba(217,98,82,0.22);
  }

  /* Filter bar (Stream) */
  .cf-audit-filterbar {
    position: sticky;
    top: 0;
    z-index: 20;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    margin-bottom: 14px;
    background: ${panelBg};
    backdrop-filter: blur(14px) saturate(140%);
    -webkit-backdrop-filter: blur(14px) saturate(140%);
    border: 1px solid ${lineSoft};
    border-radius: 14px;
  }
  .cf-audit-search {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    background: ${searchBg};
    border: 1px solid ${lineSoft};
    border-radius: 10px;
    flex: 1 1 260px;
    min-width: 220px;
    color: ${mutedSoft};
  }
  .cf-audit-search input {
    flex: 1;
    border: none;
    outline: none;
    background: transparent;
    font: inherit;
    font-size: 13px;
    color: ${inkSoft};
  }
  .cf-audit-select {
    appearance: none;
    background: ${searchBg};
    border: 1px solid ${lineSoft};
    border-radius: 10px;
    padding: 7px 28px 7px 12px;
    font-size: 12px;
    color: ${inkSoft};
    cursor: pointer;
    background-image: ${selectArrow};
    background-repeat: no-repeat;
    background-position: right 10px center;
  }
  .cf-audit-select option {
    background: ${isDark ? "#0f1612" : "#ffffff"};
    color: ${inkSoft};
  }
  .cf-audit-select:disabled { opacity: 0.5; cursor: not-allowed; }
  .cf-audit-pills {
    display: inline-flex;
    padding: 3px;
    background: ${searchBg};
    border: 1px solid ${lineSoft};
    border-radius: 999px;
    gap: 2px;
  }
  .cf-audit-pill {
    appearance: none;
    border: none;
    background: transparent;
    padding: 5px 12px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: ${mutedSoft};
    cursor: pointer;
    transition: background .15s, color .15s;
  }
  .cf-audit-pill:hover { color: ${inkSoft}; }
  .cf-audit-pill-active { background: ${pillActiveBg}; color: ${pillActiveFg}; }
  .cf-audit-pill-active:hover { color: ${pillActiveFg}; }
  .cf-audit-clear {
    appearance: none;
    border: 1px solid ${lineSoft};
    background: ${searchBg};
    color: ${danger};
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    cursor: pointer;
  }
  .cf-audit-clear:hover { background: ${dangerBg}; }
  .cf-audit-refresh {
    appearance: none;
    width: 32px; height: 32px;
    border-radius: 999px;
    border: 1px solid ${lineSoft};
    background: ${searchBg};
    color: ${eyebrow};
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background .15s;
  }
  .cf-audit-refresh:hover { background: ${refreshHover}; }
  .cf-audit-refresh:disabled { opacity: 0.5; cursor: wait; }
  .cf-audit-spin { animation: cfAuditSpin .9s linear infinite; }
  @keyframes cfAuditSpin { to { transform: rotate(360deg); } }

  .cf-audit-pinbanner {
    margin-bottom: 12px;
    padding: 8px 14px;
    background: ${pinBg};
    border: 1px solid ${pinBorder};
    border-radius: 10px;
    font-size: 12px;
    color: ${inkSoft};
  }

  /* List + Card */
  .cf-audit-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .cf-audit-card {
    background: ${cardBg};
    border: 1px solid ${lineSoft};
    border-radius: 14px;
    overflow: hidden;
    transition: border-color .15s, box-shadow .15s, background .6s;
  }
  .cf-audit-card:hover {
    border-color: ${isDark ? "#3a4a40" : "#d9ccb1"};
    box-shadow: 0 6px 24px ${isDark ? "rgba(0,0,0,0.35)" : "rgba(20,30,25,0.05)"};
  }
  .cf-audit-flash {
    background: ${flashBg} !important;
    border-color: ${eyebrowDot} !important;
  }
  .cf-audit-card-head {
    width: 100%;
    appearance: none;
    background: transparent;
    border: none;
    text-align: left;
    padding: 14px 18px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: inherit;
  }
  .cf-audit-card-head[aria-disabled="true"] { cursor: default; }
  .cf-audit-card-head:focus-visible {
    outline: none;
    box-shadow: inset 0 0 0 2px rgba(78,148,112,0.35);
  }
  .cf-audit-card-row1 {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .cf-audit-action-pill {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 3px 9px;
    border-radius: 999px;
    font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
  }
  .cf-audit-resource-pill {
    font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 9px;
    border-radius: 999px;
    background: ${resourceBg};
    color: ${resourceFg};
  }
  .cf-audit-time {
    font-size: 11px;
    color: ${mutedSoft};
    font-feature-settings: "tnum";
  }
  .cf-audit-source {
    margin-left: auto;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: ${muted2};
  }
  .cf-audit-chevron {
    transition: transform .18s cubic-bezier(.2,.8,.2,1);
    color: ${mutedSoft};
  }
  .cf-audit-chevron-open { transform: rotate(180deg); }
  .cf-audit-card-row2 {
    display: flex;
    align-items: baseline;
    gap: 10px;
    flex-wrap: wrap;
  }
  .cf-audit-admin { font-size: 13px; font-weight: 600; color: ${ink}; }
  .cf-audit-summary { font-size: 14px; color: ${summaryFg}; line-height: 1.5; }

  .cf-audit-card-body {
    padding: 0 18px 16px;
    border-top: 1px solid ${lineSoft2};
    margin-top: -4px;
    padding-top: 14px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .cf-audit-diff-header {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: ${mutedSoft};
    margin-bottom: 6px;
  }
  .cf-audit-diff-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px 10px;
    background: ${diffBg};
    padding: 12px;
    border-radius: 10px;
    border: 1px solid ${lineSoft2};
  }
  .cf-audit-diff-col-header {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: ${muted2};
    padding-bottom: 4px;
    border-bottom: 1px solid ${lineSoft2};
  }
  .cf-audit-diff-cell {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 6px 8px;
    border-radius: 8px;
    font-size: 12px;
  }
  .cf-audit-diff-key {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: ${mutedSoft};
  }
  .cf-audit-diff-val {
    font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
    font-size: 12px;
    word-break: break-word;
    white-space: pre-wrap;
  }
  .cf-audit-diff-before { background: ${isDark ? "rgba(217,98,82,0.10)" : "rgba(217,98,82,0.06)"}; }
  .cf-audit-diff-before .cf-audit-diff-val {
    color: ${danger};
    text-decoration: line-through;
    text-decoration-color: ${isDark ? "rgba(234,160,148,0.55)" : "rgba(162,63,49,0.45)"};
  }
  .cf-audit-diff-after { background: ${isDark ? "rgba(95,163,127,0.14)" : "rgba(95,163,127,0.08)"}; }
  .cf-audit-diff-after .cf-audit-diff-val { color: ${okText}; }
  .cf-audit-kv {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    background: ${diffBg};
    border: 1px solid ${lineSoft2};
    border-radius: 10px;
    padding: 10px 12px;
  }
  .cf-audit-kv-row {
    display: grid;
    grid-template-columns: 140px 1fr;
    gap: 10px;
    font-size: 11px;
    align-items: baseline;
  }
  .cf-audit-kv-row dt {
    color: ${mutedSoft};
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .cf-audit-kv-row dd {
    margin: 0;
    font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
    color: ${inkSoft};
    word-break: break-word;
    white-space: pre-wrap;
  }
  .cf-audit-outreach {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 14px;
    background: ${outreachBg};
    border: 1px solid ${outreachBorder};
    border-radius: 10px;
  }
  .cf-audit-channel-badge {
    align-self: flex-start;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    padding: 3px 9px;
    border-radius: 999px;
    background: ${isDark ? "#d96252" : "#a23f31"};
    color: #fdfaf3;
  }
  .cf-audit-outreach-quote {
    margin: 0;
    padding: 8px 10px;
    background: ${outreachQuoteBg};
    border-left: 3px solid ${isDark ? "#d96252" : "#a23f31"};
    border-radius: 6px;
    font-size: 13px;
    line-height: 1.55;
    color: ${summaryFg};
    white-space: pre-wrap;
  }
  .cf-audit-login {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    background: ${okSoft};
    border: 1px solid ${okBorder};
    border-radius: 10px;
  }
  .cf-audit-login > div { display: flex; gap: 10px; align-items: baseline; }
  .cf-audit-login-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: ${eyebrow};
    min-width: 90px;
  }
  .cf-audit-login-val {
    font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
    font-size: 11px;
    color: ${inkSoft};
    word-break: break-all;
  }

  .cf-audit-empty {
    padding: 32px;
    text-align: center;
    background: ${cardBgSoft};
    border: 1px dashed ${lineSoft};
    border-radius: 14px;
    color: ${mutedSoft};
    font-size: 13px;
    font-style: italic;
  }
  .cf-audit-error { color: ${danger}; font-style: normal; }
  .cf-audit-footer {
    margin: 18px 0 0;
    text-align: center;
    font-size: 11px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: ${muted2};
  }

  /* PULSE styles */
  .cf-audit-pulse {
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .cf-audit-pulse-toolbar {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 10px;
  }
  .cf-audit-pulse-stamp {
    font-size: 11px;
    color: ${mutedSoft};
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .cf-kpi-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
  }
  @media (max-width: 900px) {
    .cf-kpi-strip { grid-template-columns: repeat(2, 1fr); }
  }
  .cf-kpi-tile {
    padding: 16px 18px;
    background: ${cardBg};
    border: 1px solid ${lineSoft};
    border-radius: 14px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    position: relative;
  }
  .cf-kpi-tone-danger {
    background: ${dangerSoft};
    border-color: ${dangerBorder};
  }
  .cf-kpi-tone-warn {
    background: ${warnSoft};
    border-color: ${warnBorder};
  }
  .cf-kpi-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: ${mutedSoft};
  }
  .cf-kpi-value {
    font-family: var(--font-fraunces), Georgia, serif;
    font-size: 30px;
    font-weight: 600;
    letter-spacing: -0.02em;
    color: ${ink};
    line-height: 1.1;
  }
  .cf-kpi-sub {
    font-size: 11px;
    color: ${mutedSoft};
    font-feature-settings: "tnum";
  }
  .cf-kpi-delta {
    margin-left: 6px;
    font-weight: 700;
  }
  .cf-kpi-delta-up { color: ${okText}; }
  .cf-kpi-delta-down { color: ${danger}; }

  .cf-pulse-section {
    padding: 16px 18px;
    background: ${cardBg};
    border: 1px solid ${lineSoft};
    border-radius: 14px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .cf-pulse-section-title {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: ${eyebrow};
  }
  .cf-pulse-grid-2 {
    display: grid;
    grid-template-columns: 1fr 2fr;
    gap: 14px;
  }
  @media (max-width: 1100px) {
    .cf-pulse-grid-2 { grid-template-columns: 1fr; }
  }
  .cf-pulse-empty {
    padding: 16px;
    text-align: center;
    color: ${muted2};
    font-size: 12px;
    font-style: italic;
  }
  .cf-pulse-empty-small { padding: 10px; font-size: 11px; }

  /* Hourly */
  .cf-pulse-hourly { position: relative; }
  .cf-pulse-hourly-svg {
    width: 100%;
    height: 140px;
    display: block;
    background: ${hourBg};
    border-radius: 10px;
  }
  .cf-pulse-hourly-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 10px;
  }
  .cf-pulse-legend-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 10px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: ${muted};
  }
  .cf-pulse-legend-swatch {
    width: 10px;
    height: 10px;
    border-radius: 3px;
    display: inline-block;
  }
  .cf-pulse-tooltip {
    margin-top: 10px;
    padding: 10px 12px;
    background: ${tooltipBg};
    color: ${tooltipFg};
    border-radius: 10px;
    font-size: 12px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .cf-pulse-tooltip-head { font-weight: 600; }
  .cf-pulse-tooltip-list { display: flex; flex-wrap: wrap; gap: 10px; }
  .cf-pulse-tooltip-row {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
  }

  /* Category bars */
  .cf-pulse-catbars {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .cf-pulse-catbar-row {
    width: 100%;
    appearance: none;
    border: none;
    background: transparent;
    display: grid;
    grid-template-columns: 110px 1fr 90px;
    align-items: center;
    gap: 10px;
    padding: 6px 4px;
    border-radius: 8px;
    cursor: pointer;
    text-align: left;
    color: inherit;
  }
  .cf-pulse-catbar-row:hover { background: ${rowHover}; }
  .cf-mini-chip {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 999px;
    text-align: center;
    justify-self: start;
  }
  .cf-pulse-catbar-track {
    height: 8px;
    background: ${trackBg};
    border-radius: 999px;
    overflow: hidden;
    display: block;
  }
  .cf-pulse-catbar-fill {
    display: block;
    height: 100%;
    border-radius: 999px;
    transition: width .3s ease;
  }
  .cf-pulse-catbar-counts {
    font-size: 12px;
    color: ${summaryFg};
    font-feature-settings: "tnum";
    text-align: right;
  }
  .cf-pulse-catbar-counts strong { color: ${ink}; }
  .cf-pulse-catbar-slash { margin: 0 4px; color: ${muted2}; }

  /* Top lists */
  .cf-pulse-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .cf-pulse-list-row {
    width: 100%;
    appearance: none;
    border: none;
    background: transparent;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 8px;
    border-radius: 8px;
    cursor: pointer;
    text-align: left;
    color: inherit;
    text-decoration: none;
  }
  .cf-pulse-list-row:hover { background: ${rowHover}; }
  .cf-pulse-list-row-static { cursor: default; }
  .cf-pulse-list-row-static:hover { background: transparent; }
  .cf-pulse-list-row-link { color: inherit; }
  .cf-pulse-list-primary {
    flex: 1;
    font-size: 13px;
    color: ${ink};
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cf-pulse-chip {
    font-size: 11px;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 999px;
    background: ${accent};
    color: ${accentFg};
    font-feature-settings: "tnum";
  }
  .cf-pulse-list-time {
    font-size: 11px;
    color: ${mutedSoft};
    font-feature-settings: "tnum";
  }

  /* Resources sub-grid */
  .cf-pulse-resgrid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }
  @media (max-width: 900px) {
    .cf-pulse-resgrid { grid-template-columns: 1fr; }
  }
  .cf-pulse-rescard {
    padding: 12px;
    border: 1px solid ${lineSoft2};
    border-radius: 10px;
    background: ${isDark ? "rgba(255,255,255,0.02)" : "rgba(247,243,234,0.4)"};
  }
  .cf-pulse-rescard-title {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: ${mutedSoft};
    margin-bottom: 8px;
  }

  /* Hot critical */
  .cf-pulse-hot-row {
    width: 100%;
    appearance: none;
    border: none;
    background: transparent;
    display: grid;
    grid-template-columns: 14px auto auto 1fr auto;
    align-items: center;
    gap: 10px;
    padding: 8px;
    border-radius: 8px;
    cursor: pointer;
    text-align: left;
    color: inherit;
  }
  .cf-pulse-hot-row:hover { background: ${isDark ? "rgba(217,98,82,0.10)" : "rgba(217,98,82,0.06)"}; }
  .cf-pulse-hot-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
  }
  .cf-pulse-hot-admin {
    font-size: 12px;
    font-weight: 600;
    color: ${ink};
  }
  .cf-pulse-hot-summary {
    font-size: 13px;
    color: ${summaryFg};
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Anomalies */
  .cf-anom-toolbar {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 18px;
    background: ${cardBg};
    border: 1px solid ${lineSoft};
    border-radius: 14px;
    margin-bottom: 14px;
    flex-wrap: wrap;
  }
  .cf-anom-toolbar-head { display: flex; flex-direction: column; gap: 4px; flex: 1; }
  .cf-anom-title { color: ${ink}; }
  .cf-anom-counts {
    font-size: 12px;
    color: ${mutedSoft};
  }
  .cf-anom-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: ${inkSoft};
    cursor: pointer;
  }
  .cf-anom-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .cf-anom-card {
    background: ${cardBg};
    border: 1px solid ${lineSoft};
    border-left: 4px solid ${muted2};
    border-radius: 12px;
    padding: 14px 18px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .cf-anom-row1 {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .cf-anom-rule {
    background: ${resourceBg};
    color: ${ink};
  }
  .cf-anom-sev {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 999px;
  }
  .cf-anom-dismissed-pill {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 999px;
    background: ${dismissedPillBg};
    color: ${dismissedPillFg};
  }
  .cf-anom-time { margin-left: auto; }
  .cf-anom-row2 {
    display: flex;
    align-items: baseline;
    gap: 10px;
    flex-wrap: wrap;
  }
  .cf-anom-admin {
    font-size: 13px;
    font-weight: 600;
    color: ${ink};
  }
  .cf-anom-desc {
    font-size: 14px;
    color: ${summaryFg};
    line-height: 1.5;
    flex: 1;
  }
  .cf-anom-desc-dismissed {
    text-decoration: line-through;
    text-decoration-color: rgba(122,117,101,0.5);
    color: ${mutedSoft};
  }
  .cf-anom-row3 {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    align-items: center;
  }
  .cf-anom-toggle-btn {
    appearance: none;
    border: none;
    background: transparent;
    color: ${eyebrow};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    cursor: pointer;
    padding: 4px 0;
  }
  .cf-anom-toggle-btn:hover { color: ${okText}; }
  .cf-anom-btn {
    appearance: none;
    border: 1px solid ${lineSoft};
    background: ${searchBg};
    color: ${inkSoft};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    padding: 6px 12px;
    border-radius: 999px;
    cursor: pointer;
  }
  .cf-anom-btn:hover { background: ${refreshHover}; }
  .cf-anom-btn:disabled { opacity: 0.5; cursor: wait; }
  .cf-anom-btn-dismiss { color: ${danger}; }
  .cf-anom-btn-dismiss:hover { background: ${dangerBg}; }
  .cf-anom-btn-undo { color: ${eyebrow}; }
  .cf-anom-btn-view {
    background: ${btnViewBg};
    color: ${btnViewFg};
    border-color: ${btnViewBg};
    margin-left: auto;
  }
  .cf-anom-btn-view:hover { background: ${btnViewHover}; border-color: ${btnViewHover}; }
  .cf-anom-detail {
    border-top: 1px solid ${lineSoft2};
    padding-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .cf-anom-detail-row {
    display: flex;
    gap: 10px;
    font-size: 12px;
    align-items: baseline;
  }
  .cf-anom-detail-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: ${mutedSoft};
    min-width: 100px;
  }
  .cf-anom-detail-val { color: ${inkSoft}; }
`;
}
