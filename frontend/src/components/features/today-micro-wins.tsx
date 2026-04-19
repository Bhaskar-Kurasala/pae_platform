"use client";

import { useEffect, useState } from "react";
import { Award, CheckCircle2, Target, Brain } from "lucide-react";
import { useMicroWins } from "@/lib/hooks/use-today";
import type { MicroWinItem } from "@/lib/api-client";

function formatWhen(iso: string, nowMs: number): string {
  const then = new Date(iso);
  const diffMin = Math.max(0, Math.round((nowMs - then.getTime()) / 60000));
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const days = Math.round(diffHr / 24);
  return `${days}d ago`;
}

function iconFor(kind: string) {
  switch (kind) {
    case "lesson_completed":
      return CheckCircle2;
    case "exercise_passed":
      return Target;
    case "quiz_perfect":
      return Brain;
    default:
      return Award;
  }
}

export function TodayMicroWins() {
  const { data, isLoading } = useMicroWins();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  if (isLoading) {
    return (
      <article
        className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6"
        aria-busy="true"
      >
        <div className="h-3 w-28 rounded bg-foreground/[0.06] animate-pulse" />
        <div className="mt-3 space-y-2">
          <div className="h-4 w-2/3 rounded bg-foreground/[0.06] animate-pulse" />
          <div className="h-4 w-1/2 rounded bg-foreground/[0.06] animate-pulse" />
        </div>
      </article>
    );
  }

  const wins: MicroWinItem[] = data?.wins ?? [];

  return (
    <article
      aria-labelledby="wins-heading"
      className="rounded-2xl border border-foreground/10 bg-card p-5 md:p-6"
    >
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
        Recent wins
      </p>
      <h2
        id="wins-heading"
        className="mt-1.5 text-base font-semibold inline-flex items-center gap-2"
      >
        <Award className="h-4 w-4 text-primary" aria-hidden="true" />
        {wins.length > 0 ? `${wins.length} small wins this week` : "Your wins will show up here"}
      </h2>

      {wins.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground leading-relaxed">
          Finish a lesson, pass an exercise, or ace a quiz — you'll see it land here.
        </p>
      ) : (
        <ul className="mt-4 space-y-2.5">
          {wins.map((w, i) => {
            const Icon = iconFor(w.kind);
            return (
              <li key={`${w.kind}-${i}`} className="flex items-start gap-2.5">
                <Icon
                  className="h-4 w-4 mt-0.5 text-primary shrink-0"
                  aria-hidden="true"
                />
                <div className="flex-1 min-w-0 flex items-baseline justify-between gap-3">
                  <span className="text-sm text-foreground truncate">
                    {w.label}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {formatWhen(w.occurred_at, now)}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}
