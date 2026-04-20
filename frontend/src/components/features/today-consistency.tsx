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
        className="rounded-2xl border border-foreground/10 bg-card p-4"
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
      className="rounded-2xl border border-foreground/10 bg-card p-4"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Flame className="h-4 w-4 text-primary shrink-0" aria-hidden="true" />
          <h2
            id="consistency-heading"
            className="text-sm font-semibold truncate"
          >
            {days_this_week} of {window_days} days
          </h2>
        </div>
        <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
          {pct}%
        </span>
      </div>

      <div
        className="mt-3 grid grid-cols-7 gap-1"
        role="list"
        aria-label="Activity this week"
      >
        {Array.from({ length: window_days }).map((_, i) => {
          const active = i < days_this_week;
          return (
            <div key={i} className="flex flex-col items-center gap-1">
              <div
                role="listitem"
                aria-label={`${WEEK_LABELS[i] ?? "Day"} — ${active ? "active" : "no activity"}`}
                className={cn(
                  "h-5 w-full rounded-md",
                  active ? "bg-primary" : "bg-foreground/10",
                )}
              />
              <span className="text-[9px] text-muted-foreground">{WEEK_LABELS[i]}</span>
            </div>
          );
        })}
      </div>
    </article>
  );
}
