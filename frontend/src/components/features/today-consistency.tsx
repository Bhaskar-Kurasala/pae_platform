"use client";

import { Flame } from "lucide-react";
import { useConsistency } from "@/lib/hooks/use-today";
import { cn } from "@/lib/utils";

const WEEK_LABELS = ["M", "T", "W", "T", "F", "S", "S"];

export function TodayConsistency() {
  const { data, isLoading } = useConsistency();

  if (isLoading || !data) {
    return (
      <article
        className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6"
        aria-busy="true"
      >
        <div className="h-3 w-28 rounded bg-foreground/[0.06] animate-pulse" />
        <div className="mt-3 h-5 w-1/3 rounded bg-foreground/[0.06] animate-pulse" />
      </article>
    );
  }

  const { days_this_week, window_days } = data;
  const pct = Math.min(100, Math.round((days_this_week / window_days) * 100));

  return (
    <article
      aria-labelledby="consistency-heading"
      className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Consistency
          </p>
          <h2
            id="consistency-heading"
            className="mt-1.5 text-base font-semibold inline-flex items-center gap-2"
          >
            <Flame className="h-4 w-4 text-primary" aria-hidden="true" />
            {days_this_week} of {window_days} days this week
          </h2>
        </div>
        <span className="shrink-0 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary">
          {pct}%
        </span>
      </div>

      <div
        className="mt-4 grid grid-cols-7 gap-1.5"
        role="list"
        aria-label="Activity this week"
      >
        {Array.from({ length: window_days }).map((_, i) => {
          const active = i < days_this_week;
          return (
            <div
              key={i}
              role="listitem"
              aria-label={`${WEEK_LABELS[i] ?? "Day"} — ${active ? "active" : "no activity"}`}
              className={cn(
                "h-2 rounded-full",
                active ? "bg-primary" : "bg-foreground/10",
              )}
            />
          );
        })}
      </div>
      <p className="mt-3 text-xs text-muted-foreground leading-relaxed">
        Small, steady sessions beat one big cram. Keep it rolling.
      </p>
    </article>
  );
}
