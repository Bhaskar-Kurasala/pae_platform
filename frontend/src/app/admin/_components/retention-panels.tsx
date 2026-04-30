"use client";

/**
 * F4 — Retention engine panels for the admin console.
 *
 * Five real, query-driven panels that turn the abstract "at-risk"
 * concept into a triage-ready list of names + recommended action.
 *
 * Each panel maps to one slip pattern from
 * docs/RETENTION-ENGINE.md. Priority order matches the F1 service's
 * SCORE_BASE — paid_silent at the top because that's where refund
 * risk lives.
 *
 * The component is intentionally read-only. Click "Open profile" →
 * navigates to /admin/students/{id} where the admin takes action
 * (write a note, trigger an agent, whatever). Per F2/F5 we'll add
 * inline CTAs (Send email, Schedule call) once those workflows exist.
 */

import Link from "next/link";
import {
  AlertTriangle,
  Award,
  BookOpen,
  Flame,
  Snowflake,
  type LucideIcon,
} from "lucide-react";
import {
  useRiskPanels,
  type RiskPanelStudent,
  type RiskPanels,
} from "@/lib/hooks/use-admin";

interface PanelDef {
  key: keyof RiskPanels;
  title: string;
  blurb: string;
  icon: LucideIcon;
  // Tailwind tone — feeds the title bar accent. Roughly: red for the
  // ones that need action today, amber for thoughtful intervention,
  // blue/green for "easy win" / "monitor."
  tone: "red" | "amber" | "blue" | "green" | "slate";
}

const PANEL_ORDER: PanelDef[] = [
  {
    key: "paid_silent",
    title: "Paid + silent",
    blurb: "Refund risk. Reach out today — every day silent compounds the regret.",
    icon: AlertTriangle,
    tone: "red",
  },
  {
    key: "capstone_stalled",
    title: "Capstone stalled",
    blurb: "Confidence churn near the payoff. They got close — help them finish.",
    icon: BookOpen,
    tone: "amber",
  },
  {
    key: "streak_broken",
    title: "Streak broken",
    blurb: "MOST recoverable. They proved they can do it — life pulled them away.",
    icon: Flame,
    tone: "amber",
  },
  {
    key: "promotion_avoidant",
    title: "Ready but stalled",
    blurb: "Passed senior review, hasn't claimed the gate. Easy wins.",
    icon: Award,
    tone: "green",
  },
  {
    key: "cold_signup",
    title: "Never returned",
    blurb: "Bigger volume, lower per-student value. Bulk-email candidates.",
    icon: Snowflake,
    tone: "slate",
  },
];

// Tone classes use explicit color stops so they look right on BOTH the
// light Tailwind admin shell AND the CareerForge console (which sets
// its own data-theme="dark" island and bypasses Tailwind's `dark`
// variant). Each entry includes a translucent panel fill that reads
// over both white and dark-green surfaces.
const TONE_CLASSES: Record<PanelDef["tone"], string> = {
  red: "border-red-400/40 bg-red-500/[0.06]",
  amber: "border-amber-400/40 bg-amber-500/[0.06]",
  blue: "border-blue-400/40 bg-blue-500/[0.06]",
  green: "border-emerald-400/40 bg-emerald-500/[0.06]",
  slate: "border-zinc-400/30 bg-zinc-500/[0.05]",
};

function avatarLabel(name: string): string {
  return name
    .split(" ")
    .map((w) => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function StudentRow({ s }: { s: RiskPanelStudent }) {
  // currentColor-based tints so the row reads correctly under both
  // the light Tailwind shell and the dark CareerForge console island.
  return (
    <Link
      href={`/admin/students/${s.user_id}`}
      className="flex items-center gap-3 rounded-lg border border-current/10 bg-current/[0.04] px-3 py-2.5 text-left transition hover:bg-current/[0.08]"
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-current/10 text-xs font-semibold">
        {avatarLabel(s.name)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium">{s.name}</span>
          {s.paid && (
            <span className="rounded-full bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-violet-500">
              Paid
            </span>
          )}
        </div>
        <div className="truncate text-xs opacity-70">
          {s.risk_reason ?? `Score ${s.risk_score}`}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div className="text-sm font-semibold tabular-nums">{s.risk_score}</div>
        <div className="text-[10px] uppercase opacity-60">risk</div>
      </div>
    </Link>
  );
}

function Panel({ def, panel }: { def: PanelDef; panel: RiskPanels[keyof RiskPanels] }) {
  const Icon = def.icon;
  return (
    <section
      className={`rounded-xl border ${TONE_CLASSES[def.tone]} p-4`}
      aria-labelledby={`panel-${def.key}-title`}
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <Icon className="mt-0.5 h-4 w-4 shrink-0 opacity-70" aria-hidden="true" />
          <div>
            <h3
              id={`panel-${def.key}-title`}
              className="text-sm font-semibold tracking-tight"
            >
              {def.title}
            </h3>
            <p className="mt-0.5 text-xs opacity-70">{def.blurb}</p>
          </div>
        </div>
        <span className="shrink-0 rounded-full bg-current/10 px-2 py-0.5 text-xs font-semibold tabular-nums">
          {panel.total}
        </span>
      </div>

      {panel.students.length === 0 ? (
        <p className="rounded-lg border border-dashed border-current/20 bg-current/[0.03] py-3 text-center text-xs opacity-70">
          {def.tone === "red"
            ? "Nice — every paid student is active."
            : "No students in this bucket right now."}
        </p>
      ) : (
        <div className="space-y-1.5">
          {panel.students.slice(0, 5).map((s) => (
            <StudentRow key={s.user_id} s={s} />
          ))}
          {panel.total > 5 && (
            <Link
              href={`/admin/at-risk?slip_type=${def.key}`}
              className="block rounded-lg py-1.5 text-center text-xs font-medium text-emerald-500 hover:underline"
            >
              See all {panel.total} →
            </Link>
          )}
        </div>
      )}
    </section>
  );
}

export function RetentionPanels() {
  const { data, isLoading, isError, error } = useRiskPanels();

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
        {[1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className="h-44 animate-pulse rounded-xl border border-current/10 bg-current/[0.05]"
          />
        ))}
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="rounded-xl border border-red-500/40 bg-red-500/[0.06] p-4 text-sm text-red-500">
        Failed to load retention panels: {(error as Error)?.message ?? "unknown error"}
      </div>
    );
  }

  return (
    <section aria-label="Retention engine — student slip patterns">
      <div className="mb-4">
        <h2 className="text-base font-semibold tracking-tight">Retention engine</h2>
        <p className="mt-0.5 text-xs opacity-70">
          Six slip patterns, ordered by urgency. Click any student to open their profile and
          intervene. Numbers refresh nightly from the F1 risk-scoring Celery task.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
        {PANEL_ORDER.map((def) => (
          <Panel key={def.key} def={def} panel={data[def.key]} />
        ))}
      </div>
    </section>
  );
}
