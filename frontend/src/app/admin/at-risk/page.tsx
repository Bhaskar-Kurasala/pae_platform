"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Clock,
  Frown,
  HelpCircle,
  Mail,
  RefreshCw,
  TrendingDown,
  UserX,
} from "lucide-react";
import { useAtRiskStudents, type AtRiskSignal } from "@/lib/hooks/use-admin";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const THRESHOLDS: { label: string; value: number }[] = [
  { label: "All", value: 0.2 },
  { label: "Watch", value: 0.35 },
  { label: "Act", value: 0.6 },
];

function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-xl bg-muted", className)}
      aria-hidden="true"
    />
  );
}

function RiskBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const tone =
    score >= 0.7
      ? "bg-destructive/15 text-destructive"
      : score >= 0.45
        ? "bg-amber-500/15 text-amber-600"
        : "bg-primary/10 text-primary";
  const label = score >= 0.7 ? "High" : score >= 0.45 ? "Medium" : "Low";
  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold",
        tone,
      )}
    >
      <span>{label}</span>
      <span className="font-mono">{pct}%</span>
    </div>
  );
}

function iconForSignal(name: string) {
  switch (name) {
    case "no_login":
      return UserX;
    case "lesson_stall":
      return Clock;
    case "help_drought":
      return HelpCircle;
    case "low_mood":
      return Frown;
    case "progress_stall":
      return TrendingDown;
    default:
      return AlertTriangle;
  }
}

function SignalRow({ signal }: { signal: AtRiskSignal }) {
  const Icon = iconForSignal(signal.name);
  const weightPct = Math.round(signal.weight * 100);
  return (
    <li className="flex items-start gap-2.5 text-xs">
      <Icon
        className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
        aria-hidden="true"
      />
      <span className="text-foreground">{signal.reason}</span>
      <span className="ml-auto shrink-0 font-mono text-muted-foreground">
        {weightPct}%
      </span>
    </li>
  );
}

export default function AdminAtRiskPage() {
  const [minScore, setMinScore] = useState(0.35);
  const { data, isLoading, isError, refetch, isRefetching } =
    useAtRiskStudents(minScore);

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6 md:p-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <AlertTriangle
              className="h-5 w-5 text-amber-500"
              aria-hidden="true"
            />
            At-risk students
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Students showing disengagement signals. Reach out before they
            churn — the reason column tells you what to lead with.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div
            role="tablist"
            aria-label="Risk threshold"
            className="flex rounded-lg border border-border bg-card p-0.5"
          >
            {THRESHOLDS.map((t) => (
              <button
                key={t.value}
                type="button"
                role="tab"
                aria-selected={minScore === t.value}
                onClick={() => setMinScore(t.value)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-medium transition",
                  minScore === t.value
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isRefetching || isLoading}
            aria-label="Refresh at-risk list"
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
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <Card>
          <CardContent className="py-6 text-sm text-destructive">
            Couldn&apos;t load at-risk list. Try refreshing.
          </CardContent>
        </Card>
      )}

      {!isLoading && !isError && (data?.length ?? 0) === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
            <AlertTriangle
              className="h-8 w-8 text-muted-foreground"
              aria-hidden="true"
            />
            <div className="font-medium">
              No students above this threshold
            </div>
            <p className="max-w-md text-sm text-muted-foreground">
              Either everyone&apos;s engaged, or the threshold is too strict.
              Drop it to <span className="font-mono">All</span> to see the
              watchlist.
            </p>
          </CardContent>
        </Card>
      )}

      {!isLoading && !isError && (data?.length ?? 0) > 0 && (
        <div className="space-y-3">
          {data!.map((s) => (
            <Card key={s.student_id}>
              <CardHeader className="flex flex-col gap-3 pb-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <h2 className="truncate text-base font-semibold">
                    {s.full_name || "(no name)"}
                  </h2>
                  <a
                    href={`mailto:${s.email}`}
                    className="mt-0.5 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
                  >
                    <Mail className="h-3.5 w-3.5" aria-hidden="true" />
                    {s.email}
                  </a>
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    {s.no_login_days !== null && (
                      <span>
                        Last login{" "}
                        <span className="font-mono text-foreground">
                          {s.no_login_days}d
                        </span>{" "}
                        ago
                      </span>
                    )}
                    {s.no_login_days === null && (
                      <span className="text-destructive">Never logged in</span>
                    )}
                    <span>
                      Progress{" "}
                      <span className="font-mono text-foreground">
                        {s.progress_pct.toFixed(0)}%
                      </span>
                    </span>
                    <span>
                      Help{" "}
                      <span className="font-mono text-foreground">
                        {s.help_requests_prior} → {s.help_requests_recent}
                      </span>
                    </span>
                  </div>
                </div>
                <div className="shrink-0">
                  <RiskBadge score={s.risk_score} />
                </div>
              </CardHeader>
              {s.signals.length > 0 && (
                <CardContent className="pt-0">
                  <ul className="space-y-1.5 border-t border-border/60 pt-3">
                    {s.signals.map((sig, i) => (
                      <SignalRow key={i} signal={sig} />
                    ))}
                  </ul>
                </CardContent>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
