"use client";

import { useState } from "react";
import { Flame, MessageCircle, Users, Clock, RefreshCw } from "lucide-react";
import { useConfusionHeatmap } from "@/lib/hooks/use-admin";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const WINDOWS: { label: string; days: number }[] = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
];

function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-xl bg-muted", className)}
      aria-hidden="true"
    />
  );
}

function HeatTone({ score, max }: { score: number; max: number }) {
  const pct = max > 0 ? score / max : 0;
  const tone =
    pct >= 0.66
      ? "bg-destructive/15 text-destructive"
      : pct >= 0.33
        ? "bg-amber-500/15 text-amber-600"
        : "bg-primary/10 text-primary";
  const barPct = Math.round(pct * 100);
  return (
    <div className="flex items-center gap-3">
      <div className="h-2 flex-1 rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", tone.split(" ")[0])}
          style={{ width: `${barPct}%` }}
        />
      </div>
      <span className={cn("min-w-[3rem] text-right font-mono text-xs", tone)}>
        {score.toFixed(1)}
      </span>
    </div>
  );
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "—";
  const diffMs = Date.now() - ts;
  const hours = Math.floor(diffMs / 3_600_000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  const weeks = Math.floor(days / 7);
  return `${weeks}w ago`;
}

export default function AdminConfusionPage() {
  const [days, setDays] = useState(30);
  const { data, isLoading, isError, refetch, isRefetching } =
    useConfusionHeatmap(days);

  const max = data?.length ? Math.max(...data.map((b) => b.score)) : 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6 md:p-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Flame className="h-5 w-5 text-destructive" aria-hidden="true" />
            Confusion heatmap
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Concepts generating the most help requests. Use this to decide what
            to re-teach, re-write, or add an exercise for.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div
            role="tablist"
            aria-label="Time window"
            className="flex rounded-lg border border-border bg-card p-0.5"
          >
            {WINDOWS.map((w) => (
              <button
                key={w.days}
                type="button"
                role="tab"
                aria-selected={days === w.days}
                onClick={() => setDays(w.days)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-medium transition",
                  days === w.days
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {w.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isRefetching || isLoading}
            aria-label="Refresh heatmap"
            className="rounded-lg border border-border p-2 transition hover:bg-muted disabled:opacity-50"
          >
            <RefreshCw
              className={cn("h-4 w-4", isRefetching && "animate-spin")}
              aria-hidden="true"
            />
          </button>
        </div>
      </div>

      {isLoading && (
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <Card>
          <CardContent className="py-6 text-sm text-destructive">
            Couldn&apos;t load confusion heatmap. Try refreshing.
          </CardContent>
        </Card>
      )}

      {!isLoading && !isError && (data?.length ?? 0) === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
            <Flame
              className="h-8 w-8 text-muted-foreground"
              aria-hidden="true"
            />
            <div className="font-medium">No help requests in this window</div>
            <p className="max-w-md text-sm text-muted-foreground">
              Either students aren&apos;t asking for help, or they&apos;re
              coasting on concepts below grasp level. Either way — check
              engagement before celebrating.
            </p>
          </CardContent>
        </Card>
      )}

      {!isLoading && !isError && (data?.length ?? 0) > 0 && (
        <div className="space-y-3">
          {data!.map((bucket, idx) => (
            <Card key={bucket.topic}>
              <CardHeader className="flex flex-row items-start justify-between gap-4 pb-3">
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 flex h-6 w-6 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">
                    {idx + 1}
                  </span>
                  <div>
                    <h2 className="text-base font-semibold">{bucket.topic}</h2>
                    <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span className="inline-flex items-center gap-1">
                        <MessageCircle
                          className="h-3.5 w-3.5"
                          aria-hidden="true"
                        />
                        {bucket.help_count} help request
                        {bucket.help_count === 1 ? "" : "s"}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <Users className="h-3.5 w-3.5" aria-hidden="true" />
                        {bucket.distinct_students} student
                        {bucket.distinct_students === 1 ? "" : "s"}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                        last {relativeTime(bucket.last_seen)}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="w-40 shrink-0">
                  <HeatTone score={bucket.score} max={max} />
                </div>
              </CardHeader>
              {bucket.sample_questions.length > 0 && (
                <CardContent className="pt-0">
                  <details className="group">
                    <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                      Sample questions ({bucket.sample_questions.length})
                    </summary>
                    <ul className="mt-2 space-y-1.5">
                      {bucket.sample_questions.map((q, i) => (
                        <li
                          key={i}
                          className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs italic leading-snug text-muted-foreground"
                        >
                          &ldquo;{q}&rdquo;
                        </li>
                      ))}
                    </ul>
                  </details>
                </CardContent>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
