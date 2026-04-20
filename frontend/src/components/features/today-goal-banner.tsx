"use client";

import Link from "next/link";
import { Pencil } from "lucide-react";
import type { GoalContract, Motivation } from "@/lib/api-client";
import { cn } from "@/lib/utils";

const MOTIVATION_LABEL: Record<Motivation, string> = {
  career_switch: "Career switch",
  skill_up: "Level up at work",
  interview: "Interview prep",
  curiosity: "Deep curiosity",
};

function daysBetween(future: Date, now: Date): number {
  const ms = future.getTime() - now.getTime();
  return Math.ceil(ms / 86_400_000);
}

function formatDeadline(months: number, createdAt: string): {
  target: Date;
  daysRemaining: number;
  totalDays: number;
} {
  const start = new Date(createdAt);
  const target = new Date(start);
  target.setMonth(target.getMonth() + months);
  const now = new Date();
  const totalDays = Math.max(1, daysBetween(target, start));
  const daysRemaining = Math.max(0, daysBetween(target, now));
  return { target, daysRemaining, totalDays };
}

function PaceChip({
  percent,
  daysRemaining,
  totalDays,
}: {
  percent: number;
  daysRemaining: number;
  totalDays: number;
}) {
  const label =
    daysRemaining > totalDays * 0.7
      ? "Early days"
      : percent < 60
        ? "On pace 🟢"
        : daysRemaining > 14
          ? "Keep going"
          : "Final stretch ⚡";
  return (
    <span className="inline-flex items-center rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
      {label}
    </span>
  );
}

export function TodayGoalBanner({ goal }: { goal: GoalContract }) {
  const { target, daysRemaining, totalDays } = formatDeadline(
    goal.deadline_months,
    goal.created_at,
  );
  const elapsed = totalDays - daysRemaining;
  const percent = Math.max(0, Math.min(100, (elapsed / totalDays) * 100));
  const targetLabel = target.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  return (
    <article
      aria-labelledby="goal-banner-heading"
      className={cn(
        "relative overflow-hidden rounded-2xl border border-foreground/10 bg-card p-5 md:p-6",
        "transition-shadow hover:shadow-[0_1px_0_0_rgba(255,255,255,0.02)_inset,0_8px_24px_-12px_rgba(0,0,0,0.35)]",
      )}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Your goal
          </p>
          <h2
            id="goal-banner-heading"
            className="mt-1.5 text-base font-semibold text-foreground"
          >
            {MOTIVATION_LABEL[goal.motivation]}
          </h2>
        </div>
        <Link
          href="/onboarding"
          aria-label="Edit goal"
          className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-foreground/10 px-2.5 h-7 text-xs font-medium text-muted-foreground hover:text-foreground hover:border-foreground/20 transition-colors"
        >
          <Pencil className="h-3 w-3" aria-hidden="true" />
          Edit
        </Link>
      </div>

      {/* Success statement */}
      <p className="mt-4 text-sm leading-relaxed text-foreground/90">
        &ldquo;{goal.success_statement}&rdquo;
      </p>

      {/* Pace row */}
      <div className="mt-5 space-y-3">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Time elapsed</span>
          <span className="font-medium tabular-nums">{Math.round(percent)}%</span>
        </div>
        <div
          className="h-1.5 w-full rounded-full bg-foreground/[0.06] overflow-hidden"
          role="progressbar"
          aria-valuenow={Math.round(percent)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Time elapsed toward goal deadline"
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-700"
            style={{ width: `${percent}%` }}
          />
        </div>
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {daysRemaining} days to {targetLabel}
          </p>
          <PaceChip
            percent={percent}
            daysRemaining={daysRemaining}
            totalDays={totalDays}
          />
        </div>
      </div>
    </article>
  );
}
