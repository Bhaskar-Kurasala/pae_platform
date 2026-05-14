"use client";

/**
 * /admin/agents — agent reliability / quality / cost cockpit.
 *
 * Three tabs:
 *  - Health: per-agent cards with sparklines, status, kill-switch state,
 *    cost estimate, click-through to a detail modal.
 *  - Recent activity: filterable table of agent_actions rows.
 *  - Routing: MOA classifier health (keyword hit rate, agent distribution,
 *    suspected misroutes).
 *
 * Visual system mirrors /admin/courses (Fraunces titles, Inter body,
 * warm-cream / dark-forest palette, mini-chip pills, soft 12px cards).
 */

import { useMemo, useState } from "react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import {
  useAgentsHealthExtended,
  useAgentDetail,
  useAgentRecentActivity,
  useRoutingHealth,
  useAgentRuntimeConfig,
  useUpdateAgentConfig,
  useTriggerAgentManual,
  useAdminStudents,
  useAgentTemplates,
  useCreateAgentTemplate,
  useDeleteAgentTemplate,
  useAgentContextPreview,
  useSendAgentOutput,
  type AgentHealthExtended,
  type AgentRuntimeConfigRead,
  type RecentActivityRow,
  type TaskTemplate,
  type ContextPreviewResponse,
} from "@/lib/hooks/use-admin";
import { useAdminTheme } from "@/lib/hooks/use-admin-theme";

type TabKey = "health" | "activity" | "routing";

const TEAL = "#1D9E75";
const AMBER = "#d6a54d";
const RED = "#d96252";

// ---------- helpers ----------

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "—";
  const diffMs = Date.now() - then;
  const s = Math.floor(diffMs / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function formatMoney(usd: number): string {
  if (!Number.isFinite(usd)) return "$0.00";
  if (usd >= 100) return `$${usd.toFixed(0)}`;
  if (usd >= 1) return `$${usd.toFixed(2)}`;
  return `$${usd.toFixed(3)}`;
}

function formatEval(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(2);
}

function evalTone(v: number | null | undefined): string {
  if (v == null) return "#9a9588";
  if (v >= 0.7) return TEAL;
  if (v >= 0.4) return AMBER;
  return RED;
}

// Acronym + emoji map so agent identifiers like `mcq_factory` render as
// `🧪 MCQ Factory` for admins. Unknown agents fall back to title-cased
// snake_case + a default 🤖.
const AGENT_DISPLAY: Record<string, { label: string; emoji: string }> = {
  // Creation
  content_ingestion: { label: "Content Ingestion", emoji: "📥" },
  curriculum_mapper: { label: "Curriculum Mapper", emoji: "🗺️" },
  mcq_factory: { label: "MCQ Factory", emoji: "🧪" },
  coding_assistant: { label: "Coding Assistant", emoji: "💻" },
  student_buddy: { label: "Student Buddy", emoji: "🧑‍🎓" },
  deep_capturer: { label: "Deep Capturer", emoji: "🔬" },
  cover_letter: { label: "Cover Letter", emoji: "✉️" },
  // Learning
  socratic_tutor: { label: "Socratic Tutor", emoji: "💡" },
  spaced_repetition: { label: "Spaced Repetition", emoji: "🔁" },
  knowledge_graph: { label: "Knowledge Graph", emoji: "🕸️" },
  adaptive_path: { label: "Adaptive Path", emoji: "🧭" },
  study_planner: { label: "Study Planner", emoji: "🗓️" },
  // Analytics
  adaptive_quiz: { label: "Adaptive Quiz", emoji: "🎯" },
  project_evaluator: { label: "Project Evaluator", emoji: "📊" },
  progress_report: { label: "Progress Report", emoji: "📈" },
  // Career
  mock_interview: { label: "Mock Interview", emoji: "🎤" },
  portfolio_builder: { label: "Portfolio Builder", emoji: "🏗️" },
  job_match: { label: "Job Match", emoji: "🎯" },
  career_coach: { label: "Career Coach", emoji: "🚀" },
  // Engagement
  disrupt_prevention: { label: "Disrupt Prevention", emoji: "🚨" },
  peer_matching: { label: "Peer Matching", emoji: "🤝" },
  community_celebrator: { label: "Community Celebrator", emoji: "🎉" },
  code_review: { label: "Code Review", emoji: "🔍" },
  senior_engineer: { label: "Senior Engineer", emoji: "👷" },
  // Orchestrator
  moa: { label: "Master Orchestrator", emoji: "🧠" },
};

function prettyAgentName(name: string): string {
  const entry = AGENT_DISPLAY[name];
  if (entry) return entry.label;
  return name
    .split("_")
    .map((w) => (w.length ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

function agentEmoji(name: string): string {
  return AGENT_DISPLAY[name]?.emoji ?? "🤖";
}

// DISC-57 — actor role visualization. The "unknown" bucket covers
// pre-DISC-57 historical rows; render it gracefully but quietly.
const ROLE_DISPLAY: Record<
  string,
  { label: string; emoji: string; color: string }
> = {
  student: { label: "Student", emoji: "🧑‍🎓", color: "#1D9E75" },
  admin: { label: "Admin", emoji: "👤", color: "#7c5cc4" },
  system: { label: "System", emoji: "⚙️", color: "#8f897d" },
  service: { label: "Service", emoji: "🔧", color: "#5a99af" },
  unknown: { label: "Unknown", emoji: "❔", color: "#9a9588" },
};

function roleEmoji(role: string | null): string {
  return ROLE_DISPLAY[role ?? "unknown"]?.emoji ?? "❔";
}
function roleLabel(role: string | null): string {
  return ROLE_DISPLAY[role ?? "unknown"]?.label ?? role ?? "Unknown";
}
function roleColor(role: string | null): string {
  return ROLE_DISPLAY[role ?? "unknown"]?.color ?? "#9a9588";
}

// Render the "🧑‍🎓 N · 👤 N · ⚙️ N" breakdown line. Skips roles with
// count 0 (and the "unknown" bucket unless it has a non-zero count).
// Order: student, admin, system, service, unknown.
function formatRoleBreakdown(
  by_role: Record<string, number> | undefined | null,
): string {
  if (!by_role) return "";
  const order = ["student", "admin", "system", "service", "unknown"];
  const parts: string[] = [];
  for (const k of order) {
    const n = by_role[k] ?? 0;
    if (n <= 0) continue;
    if (k === "unknown" && n === 0) continue;
    parts.push(`${ROLE_DISPLAY[k]?.emoji ?? "❔"} ${n}`);
  }
  return parts.join(" · ");
}

// Build SVG polyline path from numeric series. Skips null gaps.
function sparklinePath(
  data: (number | null)[],
  width: number,
  height: number,
): string {
  const valid = data.filter((v): v is number => v != null && Number.isFinite(v));
  if (valid.length === 0) return "";
  const max = Math.max(...valid, 1);
  const min = Math.min(...valid, 0);
  const span = Math.max(max - min, 0.0001);
  const stepX = data.length > 1 ? width / (data.length - 1) : 0;
  let path = "";
  let started = false;
  data.forEach((v, i) => {
    if (v == null || !Number.isFinite(v)) {
      started = false;
      return;
    }
    const x = i * stepX;
    const y = height - ((v - min) / span) * height;
    path += `${started ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)} `;
    started = true;
  });
  return path.trim();
}

function Sparkline({
  data,
  stroke,
  width = 100,
  height = 20,
  ariaLabel,
}: {
  data: (number | null)[];
  stroke: string;
  width?: number;
  height?: number;
  ariaLabel?: string;
}) {
  const d = sparklinePath(data, width, height);
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-label={ariaLabel}
      role="img"
      style={{ display: "block" }}
    >
      {d ? (
        <path
          d={d}
          fill="none"
          stroke={stroke}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ) : (
        <line
          x1={0}
          y1={height / 2}
          x2={width}
          y2={height / 2}
          stroke={stroke}
          strokeWidth={1}
          strokeDasharray="2 3"
          opacity={0.4}
        />
      )}
    </svg>
  );
}

// ---------- page ----------

export default function AdminAgentsPage() {
  const { theme } = useAdminTheme();
  const isDark = theme === "dark";
  const [tab, setTab] = useState<TabKey>("health");
  const [openAgent, setOpenAgent] = useState<string | null>(null);

  const pageBg = isDark
    ? "linear-gradient(180deg, #0b110e 0%, #10120e 100%)"
    : "#FBF7EE";
  const ink = isDark ? "#f0ece1" : "#10120e";
  const muted = isDark ? "#9a9588" : "#686559";
  const line = isDark ? "#2c3830" : "#dbd1bf";
  const eyebrow = isDark ? "#8fd6b1" : "#356d50";
  const cardBg = isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.7)";

  const { data, isLoading, isError } = useAgentsHealthExtended();
  const { data: runtimeCfg } = useAgentRuntimeConfig();

  const configByName = useMemo(() => {
    const out: Record<string, AgentRuntimeConfigRead> = {};
    for (const c of runtimeCfg?.items ?? []) out[c.name] = c;
    return out;
  }, [runtimeCfg]);

  return (
    <div
      className="min-h-screen w-full"
      style={{
        background: pageBg,
        color: ink,
        fontFamily: "var(--font-inter), Inter, system-ui, sans-serif",
      }}
    >
      <div className="w-full px-6 py-8 md:px-10 md:py-10 max-w-[1400px] mx-auto space-y-6">
        <header className="flex flex-col gap-1">
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: eyebrow,
            }}
          >
            Admin · Agents
          </span>
          <h1
            style={{
              fontFamily: "var(--font-fraunces), Georgia, serif",
              fontSize: 24,
              fontWeight: 500,
              letterSpacing: "-0.04em",
              lineHeight: 1.1,
            }}
          >
            Agents
          </h1>
          <p style={{ color: muted, fontSize: 13, maxWidth: 720 }}>
            Health, quality, cost, and kill-switch for all 20 AI agents.
            Auto-refreshes every 30s.
          </p>
        </header>

        {/* Stat strip */}
        <StatStrip
          isDark={isDark}
          ink={ink}
          muted={muted}
          line={line}
          cardBg={cardBg}
          totalAgents={data?.agents?.length ?? 0}
          healthy={data?.healthy_count ?? 0}
          degraded={data?.degraded_count ?? 0}
          actions24h={data?.total_actions_24h ?? 0}
          errors24h={data?.total_errors_24h ?? 0}
          cost24h={data?.total_cost_24h_usd ?? 0}
          actionsByRole24h={data?.total_actions_24h_by_role}
        />

        {/* Tabs */}
        <div
          role="tablist"
          aria-label="Agents cockpit tabs"
          className="inline-flex items-center gap-1 rounded-full p-1"
          style={{
            background: isDark
              ? "rgba(255,255,255,0.04)"
              : "rgba(255,255,255,0.7)",
            border: `1px solid ${line}`,
          }}
        >
          {(
            [
              ["health", "Health"],
              ["activity", "Recent activity"],
              ["routing", "Routing"],
            ] as [TabKey, string][]
          ).map(([k, label]) => {
            const active = tab === k;
            return (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setTab(k)}
                className="px-4 py-1.5 rounded-full transition"
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  background: active ? TEAL : "transparent",
                  color: active ? "#ffffff" : ink,
                  cursor: "pointer",
                  border: "none",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>

        {tab === "health" ? (
          <HealthTab
            agents={data?.agents ?? []}
            configByName={configByName}
            isLoading={isLoading}
            isError={isError}
            isDark={isDark}
            ink={ink}
            muted={muted}
            line={line}
            cardBg={cardBg}
            onOpen={setOpenAgent}
          />
        ) : tab === "activity" ? (
          <ActivityTab
            agentNames={(data?.agents ?? []).map((a) => a.name)}
            roleCounts={data?.total_actions_24h_by_role}
            isDark={isDark}
            ink={ink}
            muted={muted}
            line={line}
            cardBg={cardBg}
            onOpenAgent={setOpenAgent}
          />
        ) : (
          <RoutingTab
            isDark={isDark}
            ink={ink}
            muted={muted}
            line={line}
            cardBg={cardBg}
          />
        )}
      </div>

      <AgentDetailModal
        agentName={openAgent}
        config={openAgent ? configByName[openAgent] ?? null : null}
        isDark={isDark}
        onClose={() => setOpenAgent(null)}
      />
    </div>
  );
}

// =====================================================================
// STAT STRIP
// =====================================================================

function StatStrip({
  isDark,
  ink,
  muted,
  line,
  cardBg,
  totalAgents,
  healthy,
  degraded,
  actions24h,
  errors24h,
  cost24h,
  actionsByRole24h,
}: {
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
  cardBg: string;
  totalAgents: number;
  healthy: number;
  degraded: number;
  actions24h: number;
  errors24h: number;
  cost24h: number;
  actionsByRole24h?: Record<string, number>;
}) {
  const roleBreakdown = formatRoleBreakdown(actionsByRole24h);
  const tiles: {
    label: string;
    primary: string;
    sub?: string;
    tone?: string;
    extra?: string;
  }[] = [
    { label: "Total agents", primary: String(totalAgents || 20) },
    {
      label: "Status",
      primary: `${healthy} healthy`,
      sub: degraded > 0 ? `${degraded} degraded` : "0 degraded",
      tone: degraded > 0 ? AMBER : TEAL,
    },
    {
      label: "Actions · 24h",
      primary: actions24h.toLocaleString(),
      sub: errors24h > 0 ? `${errors24h} errors` : "no errors",
      tone: errors24h > 0 ? RED : muted,
      extra: roleBreakdown,
    },
    {
      label: "Spend · 24h",
      primary: `≈ ${formatMoney(cost24h)}`,
      sub: "estimate",
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {tiles.map((t) => (
        <div
          key={t.label}
          className="rounded-xl px-4 py-3"
          style={{
            background: cardBg,
            border: `1px solid ${line}`,
            boxShadow: isDark
              ? "0 1px 0 rgba(0,0,0,0.3)"
              : "0 1px 0 rgba(120,90,40,0.04)",
          }}
        >
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: muted,
              marginBottom: 6,
            }}
          >
            {t.label}
          </div>
          <div
            style={{
              fontFamily: "var(--font-fraunces), Georgia, serif",
              fontSize: 22,
              fontWeight: 500,
              letterSpacing: "-0.02em",
              color: ink,
              lineHeight: 1.1,
            }}
          >
            {t.primary}
          </div>
          {t.sub ? (
            <div
              style={{
                marginTop: 4,
                fontSize: 11,
                color: t.tone ?? muted,
                fontWeight: 600,
              }}
            >
              {t.sub}
            </div>
          ) : null}
          {t.extra ? (
            <div
              style={{
                marginTop: 2,
                fontSize: 11,
                color: muted,
                fontFamily:
                  "var(--font-inter), Inter, system-ui, sans-serif",
              }}
            >
              {t.extra}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

// =====================================================================
// HEALTH TAB
// =====================================================================

function HealthTab({
  agents,
  configByName,
  isLoading,
  isError,
  isDark,
  ink,
  muted,
  line,
  cardBg,
  onOpen,
}: {
  agents: AgentHealthExtended[];
  configByName: Record<string, AgentRuntimeConfigRead>;
  isLoading: boolean;
  isError: boolean;
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
  cardBg: string;
  onOpen: (name: string) => void;
}) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-40 animate-pulse rounded-xl"
            style={{ background: cardBg, border: `1px solid ${line}` }}
          />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div
        className="rounded-xl px-4 py-6 text-center"
        style={{ background: cardBg, border: `1px solid ${line}`, color: muted }}
      >
        Failed to load agent health. Backend endpoint may not be available yet.
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <div
        className="rounded-xl px-4 py-6 text-center"
        style={{ background: cardBg, border: `1px solid ${line}`, color: muted }}
      >
        No agent data yet.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {agents.map((a) => (
        <AgentCard
          key={a.name}
          a={a}
          cfg={configByName[a.name] ?? null}
          isDark={isDark}
          ink={ink}
          muted={muted}
          line={line}
          cardBg={cardBg}
          onOpen={() => onOpen(a.name)}
        />
      ))}
    </div>
  );
}

function AgentCard({
  a,
  cfg,
  isDark,
  ink,
  muted,
  line,
  cardBg,
  onOpen,
}: {
  a: AgentHealthExtended;
  cfg: AgentRuntimeConfigRead | null;
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
  cardBg: string;
  onOpen: () => void;
}) {
  const isDisabled = cfg ? cfg.is_enabled === false : false;
  return (
    <div
      className="rounded-xl px-4 py-3 flex flex-col gap-2"
      style={{
        background: cardBg,
        border: `1px solid ${line}`,
        boxShadow: isDark
          ? "0 1px 0 rgba(0,0,0,0.3)"
          : "0 1px 0 rgba(120,90,40,0.04)",
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <span
          style={{
            fontFamily: "var(--font-fraunces), Georgia, serif",
            fontSize: 16,
            fontWeight: 500,
            letterSpacing: "-0.02em",
            color: ink,
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span
            aria-hidden="true"
            style={{ fontSize: 22, lineHeight: 1, fontFamily: "system-ui, sans-serif" }}
          >
            {agentEmoji(a.name)}
          </span>
          <span>{prettyAgentName(a.name)}</span>
        </span>
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          <MiniChip
            label={a.status}
            tone={a.status === "healthy" ? TEAL : AMBER}
          />
          {a.is_stub ? <MiniChip label="Stub" tone={muted} /> : null}
          {isDisabled ? <MiniChip label="Disabled" tone={RED} solid /> : null}
        </div>
      </div>
      <div style={{ fontSize: 10, color: muted, fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace", marginTop: 2 }}>
        {a.name}
      </div>

      <div
        style={{
          fontSize: 12,
          color: muted,
          lineHeight: 1.4,
          minHeight: 32,
        }}
      >
        {a.description}
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {a.model ? (
          <span
            style={{
              fontFamily:
                "var(--font-jetbrains-mono), ui-monospace, monospace",
              fontSize: 10,
              padding: "2px 6px",
              borderRadius: 6,
              background: isDark
                ? "rgba(255,255,255,0.06)"
                : "rgba(26,38,32,0.06)",
              color: ink,
            }}
          >
            {a.model}
          </span>
        ) : (
          <span style={{ fontSize: 10, color: muted, fontStyle: "italic" }}>
            no model
          </span>
        )}
      </div>

      <div className="flex items-center gap-3">
        <div className="flex flex-col gap-0.5">
          <span
            style={{
              fontSize: 9,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: muted,
              fontWeight: 700,
            }}
          >
            Calls 24h
          </span>
          <Sparkline
            data={a.calls_sparkline ?? []}
            stroke={TEAL}
            ariaLabel="24-hour call volume"
          />
        </div>
        <div className="flex flex-col gap-0.5">
          <span
            style={{
              fontSize: 9,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: muted,
              fontWeight: 700,
            }}
          >
            Eval 24h
          </span>
          <Sparkline
            data={a.eval_sparkline ?? []}
            stroke={AMBER}
            ariaLabel="24-hour eval score"
          />
        </div>
      </div>

      <div
        style={{
          fontSize: 11,
          color: muted,
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          fontFamily: "var(--font-inter), Inter, sans-serif",
        }}
      >
        <span>
          <strong style={{ color: ink, fontWeight: 600 }}>
            {a.actions_24h}
          </strong>{" "}
          actions
        </span>
        <span>·</span>
        <span style={{ color: a.errors_24h > 0 ? RED : muted }}>
          {a.errors_24h} errors
        </span>
        <span>·</span>
        <span>{formatEval(a.avg_eval_score_24h)} eval</span>
        <span>·</span>
        <span>≈ {formatMoney(a.est_cost_24h_usd)} 24h</span>
      </div>

      <AgentCardRoleLine
        by_role={a.actions_24h_by_role}
        muted={muted}
      />

      <div className="flex justify-end pt-1">
        <button
          type="button"
          onClick={onOpen}
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            padding: "4px 10px",
            borderRadius: 999,
            border: `1px solid ${line}`,
            background: "transparent",
            color: ink,
            cursor: "pointer",
          }}
        >
          Open
        </button>
      </div>
    </div>
  );
}

// DISC-57 — agent card actor breakdown sub-line. Hidden entirely when
// the card has zero traffic; collapsed to "all student" / "all system"
// when only one role has count > 0 (keeps low-traffic cards clean).
function AgentCardRoleLine({
  by_role,
  muted,
}: {
  by_role: Record<string, number> | undefined | null;
  muted: string;
}) {
  if (!by_role) return null;
  const entries = Object.entries(by_role).filter(([, n]) => (n ?? 0) > 0);
  if (entries.length === 0) return null;
  if (entries.length === 1) {
    const [role] = entries[0];
    if (role === "unknown") return null;
    return (
      <div
        style={{
          fontSize: 11,
          color: muted,
          fontFamily: "var(--font-inter), Inter, system-ui, sans-serif",
        }}
      >
        all {role}
      </div>
    );
  }
  const line = formatRoleBreakdown(by_role);
  if (!line) return null;
  return (
    <div
      style={{
        fontSize: 11,
        color: muted,
        fontFamily: "var(--font-inter), Inter, system-ui, sans-serif",
      }}
    >
      {line}
    </div>
  );
}

function MiniChip({
  label,
  tone,
  solid = false,
}: {
  label: string;
  tone: string;
  solid?: boolean;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        background: solid ? tone : "transparent",
        color: solid ? "#fff" : tone,
        border: solid ? "none" : `1px solid ${tone}`,
      }}
    >
      {label}
    </span>
  );
}

// =====================================================================
// ACTIVITY TAB
// =====================================================================

function ActivityTab({
  agentNames,
  roleCounts,
  isDark,
  ink,
  muted,
  line,
  cardBg,
  onOpenAgent,
}: {
  agentNames: string[];
  // DISC-57 — page-level 24h actor breakdown, used to label the
  // role filter chips above the activity table. Counts shown here
  // reflect 24h totals from the agents/health-extended endpoint,
  // NOT the currently-loaded recent-activity slice.
  roleCounts?: Record<string, number>;
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
  cardBg: string;
  onOpenAgent: (name: string) => void;
}) {
  const [agentFilter, setAgentFilter] = useState<string>("");
  const [roleFilter, setRoleFilter] = useState<string>("");
  const [minEval, setMinEval] = useState<number>(0);
  const [limit, setLimit] = useState<number>(50);
  const [openRow, setOpenRow] = useState<RecentActivityRow | null>(null);

  const { data, isLoading, isError, refetch, isFetching } = useAgentRecentActivity({
    agent_name: agentFilter || undefined,
    min_eval_score: minEval > 0 ? minEval : undefined,
    limit,
    actor_role: roleFilter || undefined,
  });

  const items = data?.items ?? [];

  // DISC-57 — role chips. ALL + the four known roles, plus UNKNOWN
  // only when it has a non-zero count.
  const totalRoleCount = Object.values(roleCounts ?? {}).reduce(
    (acc, n) => acc + (n ?? 0),
    0,
  );
  const roleChips: { key: string; label: string; count: number }[] = [
    { key: "", label: "All", count: totalRoleCount },
    { key: "student", label: "Student", count: roleCounts?.student ?? 0 },
    { key: "admin", label: "Admin", count: roleCounts?.admin ?? 0 },
    { key: "system", label: "System", count: roleCounts?.system ?? 0 },
  ];
  if ((roleCounts?.service ?? 0) > 0) {
    roleChips.push({
      key: "service",
      label: "Service",
      count: roleCounts?.service ?? 0,
    });
  }
  if ((roleCounts?.unknown ?? 0) > 0) {
    roleChips.push({
      key: "unknown",
      label: "Unknown",
      count: roleCounts?.unknown ?? 0,
    });
  }

  return (
    <div className="space-y-3">
      <div
        className="flex flex-wrap items-center gap-2 rounded-xl px-4 py-3"
        style={{ background: cardBg, border: `1px solid ${line}` }}
      >
        {roleChips.map((c) => {
          const active = roleFilter === c.key;
          return (
            <button
              key={c.key || "all"}
              type="button"
              onClick={() => setRoleFilter(c.key)}
              style={{
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                padding: "4px 11px",
                borderRadius: 999,
                border: active ? "none" : `1px solid ${line}`,
                background: active ? TEAL : "transparent",
                color: active ? "#fff" : ink,
                cursor: "pointer",
              }}
              aria-pressed={active}
            >
              {c.label} · {c.count}
            </button>
          );
        })}
      </div>

      <div
        className="flex flex-wrap items-end gap-3 rounded-xl px-4 py-3"
        style={{ background: cardBg, border: `1px solid ${line}` }}
      >
        <div className="flex flex-col gap-1">
          <label
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: muted,
            }}
          >
            Agent
          </label>
          <select
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            style={{
              fontSize: 13,
              padding: "5px 10px",
              borderRadius: 8,
              border: `1px solid ${line}`,
              background: isDark ? "rgba(255,255,255,0.04)" : "#fff",
              color: ink,
              minWidth: 180,
            }}
          >
            <option value="">All agents</option>
            {agentNames.map((n) => (
              <option key={n} value={n}>
                {agentEmoji(n)} {prettyAgentName(n)}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: muted,
            }}
          >
            Min eval · {minEval.toFixed(2)}
          </label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={minEval}
            onChange={(e) => setMinEval(Number(e.target.value))}
            style={{ width: 180 }}
          />
        </div>

        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            padding: "6px 14px",
            borderRadius: 999,
            border: `1px solid ${line}`,
            background: "transparent",
            color: ink,
            cursor: isFetching ? "wait" : "pointer",
            opacity: isFetching ? 0.6 : 1,
          }}
        >
          {isFetching ? "Refreshing…" : "Refresh"}
        </button>

        <div style={{ marginLeft: "auto", fontSize: 11, color: muted }}>
          {data ? `${data.total_returned} rows` : null}
        </div>
      </div>

      <div
        className="rounded-xl overflow-x-auto"
        style={{ background: cardBg, border: `1px solid ${line}` }}
      >
        {isLoading ? (
          <div style={{ padding: 24, textAlign: "center", color: muted }}>
            Loading…
          </div>
        ) : isError ? (
          <div style={{ padding: 24, textAlign: "center", color: muted }}>
            Failed to load recent activity. Backend endpoint may not be
            available yet.
          </div>
        ) : items.length === 0 ? (
          <div style={{ padding: 24, textAlign: "center", color: muted }}>
            No matching agent actions.
          </div>
        ) : (
          <table className="w-full text-sm" aria-label="Recent agent activity">
            <thead>
              <tr style={{ borderBottom: `1px solid ${line}` }}>
                <Th muted={muted}>Time</Th>
                <Th muted={muted}>Trigger</Th>
                <Th muted={muted}>Agent</Th>
                <Th muted={muted}>Student</Th>
                <Th muted={muted}>Eval</Th>
                <Th muted={muted} align="right">
                  Duration
                </Th>
                <Th muted={muted}>Status</Th>
                <Th muted={muted} align="right">
                  Action
                </Th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr
                  key={r.action_id}
                  style={{ borderBottom: `1px solid ${line}` }}
                >
                  <Td muted={muted}>{formatRelative(r.created_at)}</Td>
                  <Td>
                    <TriggerCell row={r} muted={muted} />
                  </Td>
                  <Td>
                    <button
                      type="button"
                      onClick={() => onOpenAgent(r.agent_name)}
                      style={{
                        fontFamily:
                          "var(--font-jetbrains-mono), ui-monospace, monospace",
                        fontSize: 11,
                        padding: "2px 8px",
                        borderRadius: 999,
                        background: isDark
                          ? "rgba(255,255,255,0.06)"
                          : "rgba(26,38,32,0.06)",
                        color: ink,
                        border: "none",
                        cursor: "pointer",
                      }}
                    >
                      <span aria-hidden="true" style={{ marginRight: 6, fontFamily: "system-ui, sans-serif" }}>
                        {agentEmoji(r.agent_name)}
                      </span>
                      {prettyAgentName(r.agent_name)}
                    </button>
                  </Td>
                  <Td>{r.student_name ?? "—"}</Td>
                  <Td>
                    <MiniChip
                      label={formatEval(r.evaluation_score)}
                      tone={evalTone(r.evaluation_score)}
                    />
                  </Td>
                  <Td muted={muted} align="right">
                    {r.duration_ms}ms
                  </Td>
                  <Td>
                    {r.has_error ? (
                      <span style={{ color: RED, fontWeight: 600 }}>error</span>
                    ) : (
                      <span style={{ color: TEAL, fontWeight: 600 }}>ok</span>
                    )}
                  </Td>
                  <Td align="right">
                    <button
                      type="button"
                      onClick={() => setOpenRow(r)}
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        letterSpacing: "0.12em",
                        textTransform: "uppercase",
                        padding: "3px 9px",
                        borderRadius: 999,
                        border: `1px solid ${line}`,
                        background: "transparent",
                        color: ink,
                        cursor: "pointer",
                      }}
                    >
                      View
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {items.length > 0 && items.length >= limit ? (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={() => setLimit((n) => n + 50)}
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              padding: "6px 14px",
              borderRadius: 999,
              border: `1px solid ${line}`,
              background: "transparent",
              color: ink,
              cursor: "pointer",
            }}
          >
            Load more
          </button>
        </div>
      ) : null}

      <ActivityRowModal
        row={openRow}
        onClose={() => setOpenRow(null)}
        isDark={isDark}
      />
    </div>
  );
}

// DISC-57 — "Trigger" column cell. Shows an emoji+label chip tinted by
// roleColor(). Title tooltip exposes the actor_id and on_behalf_of so an
// admin can audit "who actually fired this" without opening the modal.
// When admin/system acts on a student, render a "→ {student}" footnote
// below the chip.
function TriggerCell({
  row,
  muted,
}: {
  row: RecentActivityRow;
  ink?: string;
  muted: string;
}) {
  const color = roleColor(row.actor_role);
  const emoji = roleEmoji(row.actor_role);
  const label = roleLabel(row.actor_role);
  const tooltip = [
    `actor_id: ${row.actor_id ?? "—"}`,
    `on_behalf_of: ${row.on_behalf_of ?? "—"}`,
  ].join("\n");
  const showOnBehalf =
    (row.actor_role === "admin" || row.actor_role === "system") &&
    row.on_behalf_of &&
    row.student_name;
  return (
    <div className="flex flex-col gap-0.5" title={tooltip}>
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          alignSelf: "flex-start",
          padding: "2px 8px",
          borderRadius: 999,
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color,
          border: `1px solid ${color}`,
          background: `${color}14`,
        }}
      >
        <span
          aria-hidden="true"
          style={{ fontFamily: "system-ui, sans-serif" }}
        >
          {emoji}
        </span>
        {label}
      </span>
      {showOnBehalf ? (
        <span style={{ fontSize: 10, color: muted }}>
          → {row.student_name}
        </span>
      ) : null}
    </div>
  );
}

function Th({
  children,
  align = "left",
  muted,
}: {
  children: React.ReactNode;
  align?: "left" | "right" | "center";
  muted?: string;
}) {
  return (
    <th
      style={{
        textAlign: align,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.18em",
        textTransform: "uppercase",
        color: muted,
        padding: "10px 12px",
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align = "left",
  muted,
}: {
  children: React.ReactNode;
  align?: "left" | "right" | "center";
  muted?: string;
}) {
  return (
    <td
      style={{
        textAlign: align,
        padding: "10px 12px",
        color: muted,
        fontSize: 13,
        verticalAlign: "middle",
      }}
    >
      {children}
    </td>
  );
}

// =====================================================================
// ROUTING TAB
// =====================================================================

function RoutingTab({
  isDark,
  ink,
  muted,
  line,
  cardBg,
}: {
  isDark: boolean;
  ink: string;
  muted: string;
  line: string;
  cardBg: string;
}) {
  const { data, isLoading, isError } = useRoutingHealth();

  if (isLoading) {
    return (
      <div
        className="rounded-xl px-4 py-6 text-center"
        style={{ background: cardBg, border: `1px solid ${line}`, color: muted }}
      >
        Loading routing data…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div
        className="rounded-xl px-4 py-6 text-center"
        style={{ background: cardBg, border: `1px solid ${line}`, color: muted }}
      >
        Failed to load routing health. Backend endpoint may not be available
        yet.
      </div>
    );
  }

  const dist = Object.entries(data.agent_distribution_24h).sort(
    (a, b) => b[1] - a[1],
  );
  const distMax = Math.max(...dist.map(([, n]) => n), 1);
  const misroutes = Object.entries(data.misroutes_by_agent)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);
  const misMax = Math.max(...misroutes.map(([, n]) => n), 1);

  const hitRatePct = Math.round(data.keyword_hit_rate * 100);

  return (
    <div className="space-y-4">
      <h2
        style={{
          fontFamily: "var(--font-fraunces), Georgia, serif",
          fontSize: 18,
          fontWeight: 500,
          letterSpacing: "-0.02em",
          color: ink,
        }}
      >
        MOA classifier health
      </h2>

      <div
        className="rounded-xl px-4 py-3 grid grid-cols-1 md:grid-cols-3 gap-3"
        style={{ background: cardBg, border: `1px solid ${line}` }}
      >
        <KpiRow
          label="Total routes 24h"
          value={data.total_routes_24h.toLocaleString()}
          muted={muted}
          ink={ink}
        />
        <KpiRow
          label="Keyword hit rate"
          value={`${hitRatePct}%`}
          sub={`${data.keyword_hits_24h} hits · ${data.llm_fallback_24h} fallbacks`}
          muted={muted}
          ink={ink}
        />
        <KpiRow
          label="Suspected misroutes"
          value={data.suspected_misroutes_24h.toLocaleString()}
          sub="eval < 0.4"
          muted={muted}
          ink={ink}
          tone={data.suspected_misroutes_24h > 0 ? AMBER : undefined}
        />
      </div>

      <div
        className="rounded-xl px-4 py-3"
        style={{ background: cardBg, border: `1px solid ${line}` }}
      >
        <h3
          style={{
            fontFamily: "var(--font-fraunces), Georgia, serif",
            fontSize: 16,
            fontWeight: 500,
            color: ink,
            marginBottom: 10,
          }}
        >
          Agent distribution · 24h
        </h3>
        {dist.length === 0 ? (
          <div style={{ color: muted, fontSize: 13 }}>No routes yet.</div>
        ) : (
          <ul className="space-y-1.5">
            {dist.map(([name, n]) => (
              <BarRow
                key={name}
                name={name}
                count={n}
                pct={n / distMax}
                color={TEAL}
                ink={ink}
                muted={muted}
                line={line}
              />
            ))}
          </ul>
        )}
      </div>

      <div
        className="rounded-xl px-4 py-3"
        style={{ background: cardBg, border: `1px solid ${line}` }}
      >
        <h3
          style={{
            fontFamily: "var(--font-fraunces), Georgia, serif",
            fontSize: 16,
            fontWeight: 500,
            color: ink,
            marginBottom: 10,
          }}
        >
          Misroutes by agent · 24h
        </h3>
        {misroutes.length === 0 ? (
          <div style={{ color: muted, fontSize: 13 }}>
            No suspected misroutes — eval scores are healthy.
          </div>
        ) : (
          <ul className="space-y-1.5">
            {misroutes.map(([name, n]) => (
              <BarRow
                key={name}
                name={name}
                count={n}
                pct={n / misMax}
                color={AMBER}
                ink={ink}
                muted={muted}
                line={line}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function KpiRow({
  label,
  value,
  sub,
  ink,
  muted,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  ink: string;
  muted: string;
  tone?: string;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: muted,
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-fraunces), Georgia, serif",
          fontSize: 22,
          fontWeight: 500,
          letterSpacing: "-0.02em",
          color: tone ?? ink,
          lineHeight: 1.1,
        }}
      >
        {value}
      </div>
      {sub ? (
        <div style={{ fontSize: 11, color: muted, marginTop: 2 }}>{sub}</div>
      ) : null}
    </div>
  );
}

function BarRow({
  name,
  count,
  pct,
  color,
  ink,
  muted,
  line,
}: {
  name: string;
  count: number;
  pct: number;
  color: string;
  ink: string;
  muted: string;
  line: string;
}) {
  return (
    <li className="flex items-center gap-3">
      <div
        style={{
          width: 200,
          fontSize: 12,
          color: ink,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={name}
      >
        <span aria-hidden="true" style={{ marginRight: 6, fontFamily: "system-ui, sans-serif" }}>
          {agentEmoji(name)}
        </span>
        {prettyAgentName(name)}
      </div>
      <div
        style={{
          flex: 1,
          height: 8,
          background: `1px solid ${line}`,
          backgroundColor: "rgba(127,127,127,0.08)",
          borderRadius: 999,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${Math.max(2, pct * 100).toFixed(1)}%`,
            height: "100%",
            background: color,
            borderRadius: 999,
          }}
        />
      </div>
      <div
        style={{
          width: 50,
          textAlign: "right",
          fontSize: 12,
          color: muted,
          fontFamily:
            "var(--font-jetbrains-mono), ui-monospace, monospace",
        }}
      >
        {count}
      </div>
    </li>
  );
}

// =====================================================================
// ACTIVITY ROW MODAL — full input/output for one agent action
// =====================================================================

function ActivityRowModal({
  row,
  onClose,
  isDark,
}: {
  row: RecentActivityRow | null;
  onClose: () => void;
  isDark: boolean;
}) {
  const open = !!row;
  const ink = isDark ? "#f0ece1" : "#10120e";
  const muted = isDark ? "#9a9588" : "#686559";
  const line = isDark ? "#2c3830" : "#dbd1bf";
  const bg = isDark ? "#161b18" : "#fdfaf3";

  return (
    <DialogPrimitive.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop
          className="fixed inset-0 z-50"
          style={{ background: "rgba(8,12,10,0.42)" }}
        />
        <DialogPrimitive.Popup
          className="fixed top-1/2 left-1/2 z-50 w-[calc(100vw-3rem)] max-w-[760px] -translate-x-1/2 -translate-y-1/2 outline-none flex flex-col overflow-hidden"
          style={{
            background: bg,
            color: ink,
            borderRadius: 18,
            border: `1px solid ${line}`,
            maxHeight: "calc(100vh - 2rem)",
            boxShadow: "0 30px 80px rgba(0,0,0,0.25)",
          }}
        >
          {row ? (
            <>
              <div
                className="flex items-start gap-3 px-6 py-4"
                style={{ borderBottom: `1px solid ${line}` }}
              >
                <div className="min-w-0 flex-1">
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      letterSpacing: "0.18em",
                      textTransform: "uppercase",
                      color: muted,
                      marginBottom: 4,
                    }}
                  >
                    Agent action · {formatRelative(row.created_at)}
                  </div>
                  <DialogPrimitive.Title
                    style={{
                      fontFamily: "var(--font-fraunces), Georgia, serif",
                      fontSize: 22,
                      fontWeight: 500,
                      letterSpacing: "-0.02em",
                    }}
                  >
                    {row.agent_name}
                  </DialogPrimitive.Title>
                </div>
                <DialogPrimitive.Close
                  className="inline-flex h-8 w-8 items-center justify-center rounded-full"
                  aria-label="Close"
                  style={{ color: ink, background: "transparent", border: "none" }}
                >
                  <X size={16} />
                </DialogPrimitive.Close>
              </div>

              <div className="px-6 py-5 overflow-y-auto space-y-4">
                {row.actor_role ? (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      fontSize: 13,
                      color: roleColor(row.actor_role),
                      fontWeight: 600,
                    }}
                  >
                    <span
                      aria-hidden="true"
                      style={{
                        fontFamily: "system-ui, sans-serif",
                        fontSize: 18,
                      }}
                    >
                      {roleEmoji(row.actor_role)}
                    </span>
                    <span>
                      {roleLabel(row.actor_role)}
                      {row.actor_role === "student" && row.student_name ? (
                        <>
                          {" · "}
                          <span style={{ color: ink }}>{row.student_name}</span>
                        </>
                      ) : (row.actor_role === "admin" ||
                          row.actor_role === "system") &&
                        row.on_behalf_of &&
                        row.student_name ? (
                        <>
                          {" · acting on "}
                          <span style={{ color: ink }}>{row.student_name}</span>
                        </>
                      ) : null}
                    </span>
                  </div>
                ) : null}
                <div
                  style={{
                    display: "flex",
                    gap: 12,
                    flexWrap: "wrap",
                    fontSize: 12,
                    color: muted,
                  }}
                >
                  <span>
                    Student:{" "}
                    <strong style={{ color: ink }}>
                      {row.student_name ?? "—"}
                    </strong>
                  </span>
                  <span>·</span>
                  <span>
                    Eval:{" "}
                    <strong style={{ color: evalTone(row.evaluation_score) }}>
                      {formatEval(row.evaluation_score)}
                    </strong>
                  </span>
                  <span>·</span>
                  <span>Duration: {row.duration_ms}ms</span>
                  <span>·</span>
                  <span>
                    Status:{" "}
                    <strong style={{ color: row.has_error ? RED : TEAL }}>
                      {row.has_error ? "error" : "ok"}
                    </strong>
                  </span>
                </div>

                {row.has_error && row.error_preview ? (
                  <Section title="Error" muted={muted} ink={ink} line={line}>
                    <Pre>{row.error_preview}</Pre>
                  </Section>
                ) : null}

                <Section title="Input" muted={muted} ink={ink} line={line}>
                  <Pre>{row.input_preview || "—"}</Pre>
                </Section>

                <Section title="Output" muted={muted} ink={ink} line={line}>
                  <Pre>{row.output_preview || "—"}</Pre>
                </Section>
              </div>
            </>
          ) : null}
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function Section({
  title,
  children,
  muted,
  ink,
  line,
}: {
  title: string;
  children: React.ReactNode;
  muted: string;
  ink: string;
  line: string;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: muted,
          marginBottom: 6,
        }}
      >
        {title}
      </div>
      <div
        style={{
          border: `1px solid ${line}`,
          borderRadius: 10,
          background: "rgba(127,127,127,0.04)",
          color: ink,
        }}
      >
        {children}
      </div>
    </div>
  );
}

function Pre({ children }: { children: React.ReactNode }) {
  return (
    <pre
      style={{
        margin: 0,
        padding: 12,
        fontFamily:
          "var(--font-jetbrains-mono), ui-monospace, monospace",
        fontSize: 12,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        maxHeight: 280,
        overflowY: "auto",
      }}
    >
      {children}
    </pre>
  );
}

// =====================================================================
// AGENT DETAIL MODAL
// =====================================================================

function AgentDetailModal({
  agentName,
  config,
  isDark,
  onClose,
}: {
  agentName: string | null;
  config: AgentRuntimeConfigRead | null;
  isDark: boolean;
  onClose: () => void;
}) {
  const open = !!agentName;
  const { data, isLoading, isError } = useAgentDetail(agentName);

  const ink = isDark ? "#f0ece1" : "#10120e";
  const muted = isDark ? "#9a9588" : "#686559";
  const line = isDark ? "#2c3830" : "#dbd1bf";
  const bg = isDark ? "#161b18" : "#fdfaf3";
  const cardBg = isDark ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.7)";

  return (
    <DialogPrimitive.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop
          className="fixed inset-0 z-50"
          style={{ background: "rgba(8,12,10,0.42)" }}
        />
        <DialogPrimitive.Popup
          className="fixed top-1/2 left-1/2 z-50 w-[calc(100vw-3rem)] max-w-[900px] -translate-x-1/2 -translate-y-1/2 outline-none flex flex-col overflow-hidden"
          style={{
            background: bg,
            color: ink,
            borderRadius: 18,
            border: `1px solid ${line}`,
            maxHeight: "calc(100vh - 2rem)",
            boxShadow: "0 30px 80px rgba(0,0,0,0.25)",
            fontFamily: "var(--font-inter), Inter, system-ui, sans-serif",
          }}
        >
          <div
            className="flex items-start gap-3 px-6 py-4"
            style={{ borderBottom: `1px solid ${line}` }}
          >
            <div className="min-w-0 flex-1">
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.18em",
                  textTransform: "uppercase",
                  color: muted,
                  marginBottom: 4,
                }}
              >
                Admin · Agent
              </div>
              <DialogPrimitive.Title
                style={{
                  fontFamily: "var(--font-fraunces), Georgia, serif",
                  fontSize: 22,
                  fontWeight: 500,
                  letterSpacing: "-0.02em",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <span aria-hidden="true" style={{ fontSize: 28, lineHeight: 1, fontFamily: "system-ui, sans-serif" }}>
                  {agentName ? agentEmoji(agentName) : "🤖"}
                </span>
                <span>{agentName ? prettyAgentName(agentName) : ""}</span>
                {agentName ? (
                  <span style={{ fontSize: 11, color: muted, fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace", fontWeight: 400, letterSpacing: 0 }}>
                    {agentName}
                  </span>
                ) : null}
              </DialogPrimitive.Title>
            </div>
            <DialogPrimitive.Close
              className="inline-flex h-8 w-8 items-center justify-center rounded-full"
              aria-label="Close"
              style={{ color: ink, background: "transparent", border: "none" }}
            >
              <X size={16} />
            </DialogPrimitive.Close>
          </div>

          <div className="px-6 py-5 overflow-y-auto space-y-5">
            {isLoading ? (
              <div style={{ color: muted, textAlign: "center", padding: 24 }}>
                Loading agent detail…
              </div>
            ) : isError || !data ? (
              <div style={{ color: muted, textAlign: "center", padding: 24 }}>
                Failed to load agent detail. Backend endpoint may not be
                available yet.
              </div>
            ) : (
              <AgentDetailBody
                detail={data}
                config={config}
                ink={ink}
                muted={muted}
                line={line}
                cardBg={cardBg}
                isDark={isDark}
              />
            )}
          </div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function AgentDetailBody({
  detail,
  config,
  ink,
  muted,
  line,
  cardBg,
  isDark,
}: {
  detail: import("@/lib/hooks/use-admin").AgentDetailResponse;
  config: AgentRuntimeConfigRead | null;
  ink: string;
  muted: string;
  line: string;
  cardBg: string;
  isDark: boolean;
}) {
  const isDisabled = config ? config.is_enabled === false : false;
  return (
    <>
      <div className="flex items-center gap-2 flex-wrap">
        {detail.model ? (
          <span
            style={{
              fontFamily:
                "var(--font-jetbrains-mono), ui-monospace, monospace",
              fontSize: 11,
              padding: "3px 8px",
              borderRadius: 6,
              background: isDark
                ? "rgba(255,255,255,0.06)"
                : "rgba(26,38,32,0.06)",
              color: ink,
            }}
          >
            {detail.model}
          </span>
        ) : null}
        {detail.is_stub ? <MiniChip label="Stub" tone={muted} /> : null}
        {isDisabled ? <MiniChip label="Disabled" tone={RED} solid /> : null}
      </div>

      <p style={{ color: muted, fontSize: 13, lineHeight: 1.5, margin: 0 }}>
        {detail.description}
      </p>

      <RoleBadges by_role={detail.actions_24h_by_role} />

      <StatsGrid detail={detail} cardBg={cardBg} line={line} ink={ink} muted={muted} />

      <ControlsSection
        agentName={detail.name}
        config={config}
        cardBg={cardBg}
        line={line}
        ink={ink}
        muted={muted}
        isDark={isDark}
      />

      <ManualTriggerSection
        agentName={detail.name}
        cardBg={cardBg}
        line={line}
        ink={ink}
        muted={muted}
        isDark={isDark}
      />

      {detail.recent_errors.length > 0 ? (
        <ErrorsPanel
          errors={detail.recent_errors}
          cardBg={cardBg}
          line={line}
          ink={ink}
          muted={muted}
        />
      ) : null}

      {detail.recent_samples.length > 0 ? (
        <SamplesPanel
          samples={detail.recent_samples}
          cardBg={cardBg}
          line={line}
          ink={ink}
          muted={muted}
        />
      ) : null}

      {detail.prompt_content ? (
        <PromptPanel
          content={detail.prompt_content}
          path={detail.prompt_path}
          cardBg={cardBg}
          line={line}
          ink={ink}
          muted={muted}
          isDark={isDark}
        />
      ) : null}
    </>
  );
}

// DISC-57 — modal-header actor breakdown chips. Rendered as mini-chips
// styled like the existing "Stub" / "Disabled" badges. Skips zero-count
// roles. Returns null when by_role is empty / all zero.
function RoleBadges({
  by_role,
}: {
  by_role: Record<string, number> | undefined | null;
}) {
  if (!by_role) return null;
  const order = ["student", "admin", "system", "service", "unknown"];
  const items = order
    .map((k) => ({ role: k, count: by_role[k] ?? 0 }))
    .filter((x) => x.count > 0);
  if (items.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {items.map(({ role, count }) => {
        const color = roleColor(role);
        return (
          <span
            key={role}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "2px 8px",
              borderRadius: 999,
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color,
              border: `1px solid ${color}`,
              background: `${color}14`,
            }}
            title={`${count} action(s) in last 24h triggered by ${roleLabel(role)}`}
          >
            <span
              aria-hidden="true"
              style={{ fontFamily: "system-ui, sans-serif" }}
            >
              {roleEmoji(role)}
            </span>
            {count} {roleLabel(role)}
          </span>
        );
      })}
    </div>
  );
}

function StatsGrid({
  detail,
  cardBg,
  line,
  ink,
  muted,
}: {
  detail: import("@/lib/hooks/use-admin").AgentDetailResponse;
  cardBg: string;
  line: string;
  ink: string;
  muted: string;
}) {
  const stats = [
    { label: "Actions 24h", value: detail.actions_24h.toLocaleString() },
    { label: "Actions 7d", value: detail.actions_7d.toLocaleString() },
    {
      label: "Actions all-time",
      value: detail.actions_all_time.toLocaleString(),
    },
    { label: "Eval 24h", value: formatEval(detail.avg_eval_score_24h) },
    { label: "Eval 7d", value: formatEval(detail.avg_eval_score_7d) },
    { label: "Avg dur 24h", value: `${detail.avg_duration_24h_ms}ms` },
    { label: "Cost 7d", value: `≈ ${formatMoney(detail.est_cost_7d_usd)}` },
    {
      label: "Cost all-time",
      value: `≈ ${formatMoney(detail.est_cost_total_usd)}`,
    },
  ];
  return (
    <div
      className="grid grid-cols-2 md:grid-cols-4 gap-2 rounded-xl px-3 py-3"
      style={{ background: cardBg, border: `1px solid ${line}` }}
    >
      {stats.map((s) => (
        <div key={s.label}>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: muted,
            }}
          >
            {s.label}
          </div>
          <div
            style={{
              fontFamily: "var(--font-fraunces), Georgia, serif",
              fontSize: 18,
              fontWeight: 500,
              color: ink,
              letterSpacing: "-0.02em",
            }}
          >
            {s.value}
          </div>
        </div>
      ))}
    </div>
  );
}

function ControlsSection({
  agentName,
  config,
  cardBg,
  line,
  ink,
  muted,
  isDark,
}: {
  agentName: string;
  config: AgentRuntimeConfigRead | null;
  cardBg: string;
  line: string;
  ink: string;
  muted: string;
  isDark: boolean;
}) {
  const updateCfg = useUpdateAgentConfig();
  const [enabled, setEnabled] = useState<boolean>(config?.is_enabled ?? true);
  const [rateLimit, setRateLimit] = useState<string>(
    config?.rate_limit_per_minute != null
      ? String(config.rate_limit_per_minute)
      : "",
  );
  const [promptVersion, setPromptVersion] = useState<string>(
    config?.prompt_version ?? "",
  );
  const [notes, setNotes] = useState<string>(config?.notes ?? "");
  const [saved, setSaved] = useState<string | null>(null);

  function handleSave() {
    setSaved(null);
    const rateNum = rateLimit.trim() === "" ? null : Number(rateLimit);
    updateCfg.mutate(
      {
        name: agentName,
        is_enabled: enabled,
        rate_limit_per_minute:
          rateNum != null && Number.isFinite(rateNum) ? rateNum : null,
        prompt_version: promptVersion.trim() || null,
        notes: notes.trim() || null,
      },
      {
        onSuccess: () => setSaved("Saved."),
        onError: (err) => setSaved(`Error: ${err.message}`),
      },
    );
  }

  return (
    <div
      className="rounded-xl px-4 py-4 space-y-3"
      style={{ background: cardBg, border: `1px solid ${line}` }}
    >
      <div
        style={{
          fontFamily: "var(--font-fraunces), Georgia, serif",
          fontSize: 16,
          fontWeight: 500,
          color: ink,
        }}
      >
        Controls
      </div>

      <div className="flex items-center gap-3">
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: muted,
            minWidth: 110,
          }}
        >
          Enabled
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          onClick={() => setEnabled((v) => !v)}
          style={{
            width: 42,
            height: 24,
            borderRadius: 999,
            background: enabled ? TEAL : isDark ? "#3a3a3a" : "#d4cdbb",
            border: "none",
            cursor: "pointer",
            padding: 2,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: enabled ? "flex-end" : "flex-start",
            transition: "background 0.15s",
          }}
        >
          <span
            style={{
              width: 20,
              height: 20,
              borderRadius: 999,
              background: "#fff",
              boxShadow: "0 1px 2px rgba(0,0,0,0.2)",
              display: "block",
            }}
          />
        </button>
        <span style={{ fontSize: 12, color: enabled ? ink : RED }}>
          {enabled ? "Enabled" : "Disabled (requests will be rejected)"}
        </span>
      </div>

      <LabeledField label="Rate limit · per minute" muted={muted}>
        <input
          type="number"
          min={0}
          placeholder="unlimited"
          value={rateLimit}
          onChange={(e) => setRateLimit(e.target.value)}
          style={inputStyle(isDark, ink, line)}
        />
      </LabeledField>

      <LabeledField label="Prompt version" muted={muted}>
        <input
          type="text"
          placeholder="e.g. v3 or 2026-05-14"
          value={promptVersion}
          onChange={(e) => setPromptVersion(e.target.value)}
          style={inputStyle(isDark, ink, line)}
        />
      </LabeledField>

      <LabeledField label="Notes" muted={muted}>
        <textarea
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Why is this disabled / why was the limit raised…"
          style={{ ...inputStyle(isDark, ink, line), resize: "vertical" }}
        />
      </LabeledField>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={updateCfg.isPending}
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            padding: "6px 14px",
            borderRadius: 999,
            background: TEAL,
            color: "#fff",
            border: "none",
            cursor: updateCfg.isPending ? "wait" : "pointer",
            opacity: updateCfg.isPending ? 0.6 : 1,
          }}
        >
          {updateCfg.isPending ? "Saving…" : "Save config"}
        </button>
        {saved ? (
          <span style={{ fontSize: 12, color: muted }}>{saved}</span>
        ) : null}
      </div>
    </div>
  );
}

function ManualTriggerSection({
  agentName,
  cardBg,
  line,
  ink,
  muted,
  isDark,
}: {
  agentName: string;
  cardBg: string;
  line: string;
  ink: string;
  muted: string;
  isDark: boolean;
}) {
  const trigger = useTriggerAgentManual();
  const { data: students } = useAdminStudents("", "joined_desc", null);
  const { data: templates } = useAgentTemplates(agentName);
  const createTemplate = useCreateAgentTemplate();
  const deleteTemplate = useDeleteAgentTemplate();
  const [studentId, setStudentId] = useState<string>("");
  const [task, setTask] = useState<string>("");
  const [lastResult, setLastResult] = useState<
    import("@/lib/hooks/use-admin").ManualTriggerResponse | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [showNewTemplate, setShowNewTemplate] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [newBody, setNewBody] = useState("");

  // Send-to-student state (review-then-send below the result block).
  const sendOutput = useSendAgentOutput();
  const [sendBody, setSendBody] = useState<string>("");
  const [sentInfo, setSentInfo] = useState<{ channel: string; sent_at: string } | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);

  const ctxQuery = useAgentContextPreview(
    agentName,
    studentId.trim() ? studentId.trim() : null,
  );
  const ctx = ctxQuery.data;
  const tone: ContextPreviewResponse["tone"] | null = ctx?.tone ?? null;
  const notReady = tone === "not_ready";

  function handleTrigger() {
    if (!studentId.trim()) {
      setError("Pick a student first.");
      return;
    }
    if (notReady) {
      const ok = window.confirm(
        "Context looks limited for this agent. Trigger anyway?",
      );
      if (!ok) return;
    }
    setError(null);
    trigger.mutate(
      {
        agentName,
        studentId: studentId.trim(),
        task: task.trim() || undefined,
      },
      {
        onSuccess: (res) => {
          setLastResult(res);
          setSendBody(res.response_preview ?? "");
          setSentInfo(null);
          setSendError(null);
        },
        onError: (err) => setError(err.message),
      },
    );
  }

  function pickTemplate(t: TaskTemplate) {
    setTask(t.body);
  }

  function handleSaveTemplate() {
    if (!newLabel.trim() || !newBody.trim()) return;
    createTemplate.mutate(
      {
        agent_name: agentName,
        label: newLabel.trim(),
        body: newBody.trim(),
      },
      {
        onSuccess: () => {
          setNewLabel("");
          setNewBody("");
          setShowNewTemplate(false);
        },
      },
    );
  }

  function handleDeleteTemplate(t: TaskTemplate) {
    if (t.is_built_in) return;
    if (!window.confirm(`Delete template "${t.label}"?`)) return;
    deleteTemplate.mutate({ id: t.id, agent_name: agentName });
  }

  const triggerBg = notReady ? AMBER : TEAL;

  const studentName =
    (students ?? []).find((s) => s.id === studentId.trim())?.full_name ??
    ctx?.student_name ??
    "this student";

  const canSend =
    !!lastResult &&
    (lastResult.status === "success" || lastResult.status === "completed") &&
    !!lastResult.action_id &&
    !!studentId.trim();

  function handleSend(channel: "whatsapp" | "email" | "in_app") {
    if (!lastResult || !canSend) return;
    const channelLabel =
      channel === "whatsapp" ? "WhatsApp" : channel === "email" ? "email" : "in-app";
    const preview = sendBody.slice(0, 200);
    const ok = window.confirm(
      `Send this ${channelLabel} message to ${studentName}?\n\n${preview}`,
    );
    if (!ok) return;
    setSendError(null);
    sendOutput.mutate(
      {
        action_id: lastResult.action_id,
        channel,
        body_override: sendBody,
        student_id: studentId.trim(),
      },
      {
        onSuccess: (res) =>
          setSentInfo({ channel: channelLabel, sent_at: res.sent_at }),
        onError: (err) => setSendError(err.message),
      },
    );
  }

  return (
    <div
      className="rounded-xl px-4 py-4 space-y-3"
      style={{ background: cardBg, border: `1px solid ${line}` }}
    >
      <div
        style={{
          fontFamily: "var(--font-fraunces), Georgia, serif",
          fontSize: 16,
          fontWeight: 500,
          color: ink,
        }}
      >
        Manual trigger
      </div>

      {/* Templates row */}
      <div className="space-y-2">
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: muted,
          }}
        >
          Templates
        </div>
        <div
          className="flex items-center gap-2 overflow-x-auto"
          style={{ paddingBottom: 4 }}
        >
          {(templates ?? []).map((t) => (
            <TemplateChip
              key={t.id}
              t={t}
              onPick={pickTemplate}
              onDelete={handleDeleteTemplate}
              ink={ink}
              muted={muted}
              line={line}
              isDark={isDark}
            />
          ))}
          <button
            type="button"
            onClick={() => setShowNewTemplate((v) => !v)}
            title="Create a new template"
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              padding: "4px 10px",
              borderRadius: 999,
              background: "transparent",
              color: muted,
              border: `1px dashed ${line}`,
              cursor: "pointer",
              whiteSpace: "nowrap",
              flexShrink: 0,
            }}
          >
            + New template
          </button>
        </div>
        {showNewTemplate ? (
          <div
            className="space-y-2 rounded-lg px-3 py-3"
            style={{
              border: `1px solid ${line}`,
              background: "rgba(127,127,127,0.04)",
            }}
          >
            <input
              type="text"
              placeholder="Label (e.g. Re-engage after streak break)"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              style={inputStyle(isDark, ink, line)}
              maxLength={80}
            />
            <textarea
              rows={3}
              placeholder="Template body — what the agent should do…"
              value={newBody}
              onChange={(e) => setNewBody(e.target.value)}
              style={{ ...inputStyle(isDark, ink, line), resize: "vertical" }}
            />
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleSaveTemplate}
                disabled={
                  createTemplate.isPending ||
                  !newLabel.trim() ||
                  !newBody.trim()
                }
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  padding: "5px 12px",
                  borderRadius: 999,
                  background: TEAL,
                  color: "#fff",
                  border: "none",
                  cursor: createTemplate.isPending ? "wait" : "pointer",
                  opacity:
                    createTemplate.isPending ||
                    !newLabel.trim() ||
                    !newBody.trim()
                      ? 0.5
                      : 1,
                }}
              >
                {createTemplate.isPending ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowNewTemplate(false);
                  setNewLabel("");
                  setNewBody("");
                }}
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  padding: "5px 12px",
                  borderRadius: 999,
                  background: "transparent",
                  color: muted,
                  border: `1px solid ${line}`,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}
      </div>

      <LabeledField label="Student" muted={muted}>
        {students && students.length > 0 ? (
          <select
            value={studentId}
            onChange={(e) => setStudentId(e.target.value)}
            style={inputStyle(isDark, ink, line)}
          >
            <option value="">— pick a student —</option>
            {students.slice(0, 200).map((s) => (
              <option key={s.id} value={s.id}>
                {s.full_name} · {s.email}
              </option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            placeholder="student UUID"
            value={studentId}
            onChange={(e) => setStudentId(e.target.value)}
            style={inputStyle(isDark, ink, line)}
          />
        )}
      </LabeledField>

      {/* Context preview panel */}
      {studentId.trim() ? (
        <ContextPreviewPanel
          loading={ctxQuery.isLoading}
          ctx={ctx ?? null}
          agentName={agentName}
          line={line}
          ink={ink}
          muted={muted}
        />
      ) : null}

      <LabeledField label="Task (optional)" muted={muted}>
        <textarea
          rows={2}
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="Override the auto-generated task, or pick a template above…"
          style={{ ...inputStyle(isDark, ink, line), resize: "vertical" }}
        />
      </LabeledField>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleTrigger}
          disabled={trigger.isPending}
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            padding: "6px 14px",
            borderRadius: 999,
            background: triggerBg,
            color: "#fff",
            border: "none",
            cursor: trigger.isPending ? "wait" : "pointer",
            opacity: trigger.isPending ? 0.6 : 1,
          }}
          title={
            notReady
              ? "Context looks limited — you'll be asked to confirm"
              : undefined
          }
        >
          {trigger.isPending ? "Running…" : "Trigger"}
        </button>
        {error ? (
          <span style={{ fontSize: 12, color: RED }}>{error}</span>
        ) : null}
      </div>

      {lastResult ? (
        <div
          className="rounded-lg px-3 py-2"
          style={{
            background: "rgba(127,127,127,0.06)",
            border: `1px solid ${line}`,
            fontSize: 12,
          }}
        >
          <div
            style={{ color: muted, fontSize: 10, letterSpacing: "0.18em", textTransform: "uppercase", fontWeight: 700, marginBottom: 6 }}
          >
            Last run · {lastResult.status} · {lastResult.duration_ms}ms · eval{" "}
            {formatEval(lastResult.evaluation_score)}
          </div>
          <Pre>{lastResult.response_preview}</Pre>

          {canSend ? (
            <div
              className="rounded-lg px-3 py-3 mt-3 space-y-2"
              style={{
                background: "rgba(29,158,117,0.06)",
                border: `1px solid ${line}`,
              }}
            >
              <div
                style={{
                  fontFamily: "var(--font-inter), Inter, sans-serif",
                  fontSize: 12,
                  fontWeight: 600,
                  color: ink,
                }}
              >
                Send this to {studentName}
              </div>

              <textarea
                rows={4}
                value={sendBody}
                onChange={(e) => setSendBody(e.target.value)}
                disabled={sendOutput.isPending || !!sentInfo}
                style={{
                  ...inputStyle(isDark, ink, line),
                  resize: "vertical",
                  fontFamily: "var(--font-inter), Inter, sans-serif",
                  fontSize: 12,
                  opacity: sendOutput.isPending || sentInfo ? 0.7 : 1,
                }}
              />

              {sentInfo ? (
                <div
                  className="rounded-md px-3 py-2"
                  style={{
                    background: TEAL,
                    color: "#fff",
                    fontFamily: "var(--font-inter), Inter, sans-serif",
                    fontSize: 12,
                    fontWeight: 600,
                  }}
                >
                  ✓ Sent via {sentInfo.channel} at{" "}
                  {new Date(sentInfo.sent_at).toLocaleTimeString()}
                </div>
              ) : (
                <div className="flex items-center gap-2 flex-wrap">
                  {(
                    [
                      { id: "whatsapp" as const, label: "📱 WhatsApp" },
                      { id: "email" as const, label: "✉ Email" },
                      { id: "in_app" as const, label: "🔔 In-app" },
                    ]
                  ).map((c) => {
                    const disabled =
                      sendOutput.isPending || !sendBody.trim() || !!sentInfo;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => handleSend(c.id)}
                        disabled={disabled}
                        style={{
                          fontFamily: "var(--font-inter), Inter, sans-serif",
                          fontSize: 12,
                          fontWeight: 600,
                          padding: "8px 14px",
                          minHeight: 36,
                          borderRadius: 999,
                          background: isDark
                            ? "rgba(255,255,255,0.92)"
                            : "#ffffff",
                          color: "#111827",
                          border: `1px solid ${line}`,
                          cursor: disabled ? "not-allowed" : "pointer",
                          opacity: disabled ? 0.55 : 1,
                          boxShadow:
                            "0 1px 2px rgba(0,0,0,0.04), 0 1px 1px rgba(0,0,0,0.03)",
                          transition: "transform 80ms ease, box-shadow 80ms ease",
                          whiteSpace: "nowrap",
                        }}
                        onMouseEnter={(e) => {
                          if (disabled) return;
                          (e.currentTarget as HTMLButtonElement).style.transform =
                            "translateY(-1px)";
                          (e.currentTarget as HTMLButtonElement).style.boxShadow =
                            "0 4px 10px rgba(0,0,0,0.08)";
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLButtonElement).style.transform =
                            "";
                          (e.currentTarget as HTMLButtonElement).style.boxShadow =
                            "0 1px 2px rgba(0,0,0,0.04), 0 1px 1px rgba(0,0,0,0.03)";
                        }}
                      >
                        {sendOutput.isPending &&
                        sendOutput.variables?.channel === c.id
                          ? "Sending…"
                          : c.label}
                      </button>
                    );
                  })}
                </div>
              )}

              {sendError ? (
                <div style={{ fontSize: 12, color: RED }}>
                  Couldn&apos;t send: {sendError}
                </div>
              ) : null}

              <div
                style={{
                  fontFamily: "var(--font-inter), Inter, sans-serif",
                  fontSize: 10,
                  color: muted,
                }}
              >
                This send is recorded in the audit log.
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function TemplateChip({
  t,
  onPick,
  onDelete,
  ink,
  muted,
  line,
  isDark,
}: {
  t: TaskTemplate;
  onPick: (t: TaskTemplate) => void;
  onDelete: (t: TaskTemplate) => void;
  ink: string;
  muted: string;
  line: string;
  isDark: boolean;
}) {
  const [hover, setHover] = useState(false);
  const bg = t.is_built_in
    ? isDark
      ? "rgba(127,127,127,0.10)"
      : "rgba(127,127,127,0.06)"
    : isDark
      ? "rgba(29,158,117,0.18)"
      : "rgba(29,158,117,0.10)";
  return (
    <span
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        flexShrink: 0,
      }}
    >
      <button
        type="button"
        onClick={() => onPick(t)}
        title={t.body}
        style={{
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          padding: "4px 10px",
          borderRadius: 999,
          background: bg,
          color: t.is_built_in ? muted : ink,
          border: `1px solid ${line}`,
          cursor: "pointer",
          whiteSpace: "nowrap",
          paddingRight: !t.is_built_in && hover ? 22 : 10,
        }}
      >
        {t.label}
      </button>
      {!t.is_built_in && hover ? (
        <button
          type="button"
          aria-label={`Delete ${t.label}`}
          onClick={(e) => {
            e.stopPropagation();
            onDelete(t);
          }}
          style={{
            position: "absolute",
            right: 4,
            top: "50%",
            transform: "translateY(-50%)",
            width: 16,
            height: 16,
            borderRadius: 999,
            background: "transparent",
            color: muted,
            border: "none",
            cursor: "pointer",
            fontSize: 12,
            lineHeight: 1,
            padding: 0,
          }}
        >
          ×
        </button>
      ) : null}
    </span>
  );
}

function ContextPreviewPanel({
  loading,
  ctx,
  agentName,
  line,
  ink,
  muted,
}: {
  loading: boolean;
  ctx: ContextPreviewResponse | null;
  agentName: string;
  line: string;
  ink: string;
  muted: string;
}) {
  if (loading) {
    return (
      <div
        className="rounded-lg"
        style={{
          height: 12,
          background: "rgba(127,127,127,0.12)",
          border: `1px solid ${line}`,
        }}
      />
    );
  }
  if (!ctx) return null;

  const toneColor =
    ctx.tone === "ready"
      ? TEAL
      : ctx.tone === "limited"
        ? AMBER
        : RED;
  const toneEmoji =
    ctx.tone === "ready" ? "🟢" : ctx.tone === "limited" ? "🟡" : "🔴";
  const toneLabel =
    ctx.tone === "ready"
      ? "READY"
      : ctx.tone === "limited"
        ? "LIMITED"
        : "NOT READY";
  const pct = Math.round(Math.max(0, Math.min(1, ctx.readiness_score)) * 100);

  return (
    <div
      className="rounded-lg"
      style={{
        position: "relative",
        background: "rgba(127,127,127,0.04)",
        border: `1px solid ${line}`,
        padding: "10px 12px 10px 16px",
        overflow: "hidden",
      }}
    >
      <span
        aria-hidden="true"
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: 4,
          background: toneColor,
        }}
      />
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: toneColor,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span aria-hidden="true">{toneEmoji}</span>
        <span>
          {toneLabel} · {pct}%
        </span>
      </div>
      <div
        style={{
          fontFamily: "var(--font-inter), Inter, sans-serif",
          fontSize: 13,
          color: ink,
          marginTop: 4,
          lineHeight: 1.4,
        }}
      >
        {ctx.summary}
      </div>
      {ctx.factors.length > 0 ? (
        <div
          className="flex flex-wrap gap-1.5"
          style={{ marginTop: 8 }}
        >
          {ctx.factors.map((f, i) => (
            <span
              key={`${f.label}-${i}`}
              style={{
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: "0.10em",
                textTransform: "uppercase",
                padding: "2px 8px",
                borderRadius: 999,
                background: f.present
                  ? "rgba(29,158,117,0.12)"
                  : "rgba(127,127,127,0.08)",
                color: f.present ? TEAL : muted,
                border: `1px solid ${line}`,
              }}
            >
              {f.present ? "✓" : "✗"} {f.label}
            </span>
          ))}
        </div>
      ) : null}
      {ctx.tone === "not_ready" ? (
        <div
          style={{
            marginTop: 8,
            fontSize: 12,
            color: RED,
            background: "rgba(217,98,82,0.08)",
            border: `1px solid rgba(217,98,82,0.25)`,
            borderRadius: 6,
            padding: "6px 8px",
          }}
        >
          This student may produce limited output for {agentName}.
        </div>
      ) : null}
    </div>
  );
}

function ErrorsPanel({
  errors,
  cardBg,
  line,
  ink,
  muted,
}: {
  errors: import("@/lib/hooks/use-admin").AgentRecentError[];
  cardBg: string;
  line: string;
  ink: string;
  muted: string;
}) {
  return (
    <div
      className="rounded-xl px-4 py-4 space-y-2"
      style={{ background: cardBg, border: `1px solid ${line}` }}
    >
      <div
        style={{
          fontFamily: "var(--font-fraunces), Georgia, serif",
          fontSize: 16,
          fontWeight: 500,
          color: ink,
        }}
      >
        Recent errors · {errors.length}
      </div>
      <ul className="space-y-2">
        {errors.map((e) => (
          <ErrorRow key={e.action_id} e={e} muted={muted} ink={ink} line={line} />
        ))}
      </ul>
    </div>
  );
}

function ErrorRow({
  e,
  muted,
  ink,
  line,
}: {
  e: import("@/lib/hooks/use-admin").AgentRecentError;
  muted: string;
  ink: string;
  line: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li
      style={{
        borderTop: `1px solid ${line}`,
        paddingTop: 8,
      }}
    >
      <div
        style={{
          fontSize: 11,
          color: muted,
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        {e.actor_role ? (
          <span
            aria-hidden="true"
            style={{ fontFamily: "system-ui, sans-serif" }}
            title={roleLabel(e.actor_role)}
          >
            {roleEmoji(e.actor_role)}
          </span>
        ) : null}
        <span>{formatRelative(e.created_at)}</span>
        <span>·</span>
        <span style={{ color: ink }}>{e.student_name ?? "—"}</span>
      </div>
      <div
        style={{
          fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
          fontSize: 12,
          color: RED,
          marginTop: 4,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {e.error}
      </div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          marginTop: 4,
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: muted,
          background: "transparent",
          border: "none",
          cursor: "pointer",
          padding: 0,
        }}
      >
        {open ? "Hide input" : "Show input"}
      </button>
      {open ? <Pre>{e.input_preview}</Pre> : null}
    </li>
  );
}

function SamplesPanel({
  samples,
  cardBg,
  line,
  ink,
  muted,
}: {
  samples: import("@/lib/hooks/use-admin").AgentSampleAction[];
  cardBg: string;
  line: string;
  ink: string;
  muted: string;
}) {
  return (
    <div
      className="rounded-xl px-4 py-4 space-y-2"
      style={{ background: cardBg, border: `1px solid ${line}` }}
    >
      <div
        style={{
          fontFamily: "var(--font-fraunces), Georgia, serif",
          fontSize: 16,
          fontWeight: 500,
          color: ink,
        }}
      >
        Recent samples · {samples.length}
      </div>
      <ul className="space-y-2">
        {samples.map((s) => (
          <SampleRow key={s.action_id} s={s} muted={muted} ink={ink} line={line} />
        ))}
      </ul>
    </div>
  );
}

function SampleRow({
  s,
  muted,
  ink,
  line,
}: {
  s: import("@/lib/hooks/use-admin").AgentSampleAction;
  muted: string;
  ink: string;
  line: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li style={{ borderTop: `1px solid ${line}`, paddingTop: 8 }}>
      <div
        style={{
          fontSize: 11,
          color: muted,
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        {s.actor_role ? (
          <span
            aria-hidden="true"
            style={{ fontFamily: "system-ui, sans-serif" }}
            title={roleLabel(s.actor_role)}
          >
            {roleEmoji(s.actor_role)}
          </span>
        ) : null}
        <span>{formatRelative(s.created_at)}</span>
        <span>·</span>
        <span style={{ color: ink }}>{s.student_name ?? "—"}</span>
        <MiniChip label={formatEval(s.evaluation_score)} tone={evalTone(s.evaluation_score)} />
        <span>{s.duration_ms}ms</span>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          style={{
            marginLeft: "auto",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: muted,
            background: "transparent",
            border: "none",
            cursor: "pointer",
            padding: 0,
          }}
        >
          {open ? "Hide" : "Expand"}
        </button>
      </div>
      {open ? (
        <div className="space-y-2 mt-2">
          <Pre>{`input:\n${s.input_preview}`}</Pre>
          <Pre>{`output:\n${s.output_preview}`}</Pre>
        </div>
      ) : (
        <div
          style={{
            color: muted,
            fontSize: 12,
            marginTop: 4,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            fontFamily:
              "var(--font-jetbrains-mono), ui-monospace, monospace",
          }}
        >
          {s.input_preview.slice(0, 80)}
        </div>
      )}
    </li>
  );
}

function PromptPanel({
  content,
  path,
  cardBg,
  line,
  ink,
  muted,
  isDark,
}: {
  content: string;
  path: string | null;
  cardBg: string;
  line: string;
  ink: string;
  muted: string;
  isDark: boolean;
}) {
  return (
    <div
      className="rounded-xl px-4 py-4 space-y-2"
      style={{ background: cardBg, border: `1px solid ${line}` }}
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div
          style={{
            fontFamily: "var(--font-fraunces), Georgia, serif",
            fontSize: 16,
            fontWeight: 500,
            color: ink,
          }}
        >
          Prompt
        </div>
        {path ? (
          <span
            style={{
              fontFamily:
                "var(--font-jetbrains-mono), ui-monospace, monospace",
              fontSize: 10,
              padding: "2px 8px",
              borderRadius: 6,
              background: isDark
                ? "rgba(255,255,255,0.06)"
                : "rgba(26,38,32,0.06)",
              color: muted,
            }}
          >
            {path}
          </span>
        ) : null}
      </div>
      <pre
        style={{
          margin: 0,
          padding: 12,
          borderRadius: 10,
          background: "rgba(127,127,127,0.06)",
          border: `1px solid ${line}`,
          fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
          fontSize: 11.5,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          maxHeight: 400,
          overflowY: "auto",
          color: ink,
        }}
      >
        {content}
      </pre>
    </div>
  );
}

function LabeledField({
  label,
  children,
  muted,
}: {
  label: string;
  children: React.ReactNode;
  muted: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: muted,
        }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}

function inputStyle(
  isDark: boolean,
  ink: string,
  line: string,
): React.CSSProperties {
  return {
    fontSize: 13,
    padding: "6px 10px",
    borderRadius: 8,
    border: `1px solid ${line}`,
    background: isDark ? "rgba(255,255,255,0.04)" : "#fff",
    color: ink,
    fontFamily: "var(--font-inter), Inter, sans-serif",
    width: "100%",
    boxSizing: "border-box",
  };
}
