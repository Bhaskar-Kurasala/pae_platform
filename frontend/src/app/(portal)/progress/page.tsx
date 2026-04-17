"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
} from "recharts";
import { CheckCircle2, Clock, TrendingUp } from "lucide-react";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// ── Skeleton ─────────────────────────────────────────────────────
function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-xl bg-muted", className)}
      aria-hidden="true"
    />
  );
}

// ── GitHub-style streak calendar ─────────────────────────────────
function StreakCalendar({ activeDates }: { activeDates: Set<string> }) {
  // Build 52 weeks × 7 days grid ending today
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const cells: { dateStr: string; level: number }[] = [];

  for (let i = 363; i >= 0; i--) {
    const d = new Date(today.getTime() - i * 86400000);
    const dateStr = d.toDateString();
    const active = activeDates.has(dateStr);
    cells.push({ dateStr, level: active ? 1 : 0 });
  }

  // Group into weeks (columns)
  const weeks: { dateStr: string; level: number }[][] = [];
  for (let w = 0; w < 52; w++) {
    weeks.push(cells.slice(w * 7, w * 7 + 7));
  }

  const MONTH_LABELS: string[] = [];
  for (let i = 0; i < 52; i++) {
    const weekStart = cells[i * 7];
    if (weekStart) {
      const d = new Date(weekStart.dateStr);
      if (d.getDate() <= 7) {
        MONTH_LABELS[i] = d.toLocaleDateString("en-US", { month: "short" });
      } else {
        MONTH_LABELS[i] = "";
      }
    }
  }

  const cellColor = (level: number) =>
    level === 0 ? "bg-muted" : "bg-primary";

  return (
    <div className="overflow-x-auto pb-2">
      {/* Month labels */}
      <div className="flex gap-1 mb-1 min-w-max ml-8">
        {MONTH_LABELS.map((label, i) => (
          <div key={i} className="w-3 text-xs text-muted-foreground" style={{ width: "14px" }}>
            {label}
          </div>
        ))}
      </div>

      {/* Day-of-week labels + grid */}
      <div className="flex gap-1 min-w-max">
        {/* Day labels */}
        <div className="flex flex-col gap-1 mr-1">
          {["", "Mon", "", "Wed", "", "Fri", ""].map((day, i) => (
            <div key={i} className="h-3 text-xs text-muted-foreground leading-none flex items-center">
              {day}
            </div>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="flex gap-1">
          {weeks.map((week, wi) => (
            <div key={wi} className="flex flex-col gap-1">
              {week.map((cell, di) => (
                <div
                  key={di}
                  title={`${cell.dateStr}${cell.level > 0 ? " — active" : ""}`}
                  aria-label={`${cell.dateStr}${cell.level > 0 ? ", completed a lesson" : ""}`}
                  className={cn(
                    "h-3 w-3 rounded-sm transition-colors",
                    cellColor(cell.level),
                  )}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-1.5 mt-2 text-xs text-muted-foreground">
        <span>Less</span>
        <div className="h-3 w-3 rounded-sm bg-muted" aria-hidden="true" />
        <div className="h-3 w-3 rounded-sm bg-primary/40" aria-hidden="true" />
        <div className="h-3 w-3 rounded-sm bg-primary" aria-hidden="true" />
        <span>More</span>
      </div>
    </div>
  );
}

// ── Concept mastery radar data ────────────────────────────────────
// Derived from progress tags — we approximate from lesson completion count
const CONCEPT_AREAS = [
  "LangGraph",
  "RAG",
  "Prompting",
  "Agents",
  "Eval",
  "Deployment",
];

// ── Page ─────────────────────────────────────────────────────────
export default function ProgressPage() {
  const { data: progress = [], isLoading } = useMyProgress();

  const stats = useMemo(() => {
    const completed = progress.filter((p) => p.status === "completed");
    const totalTime = progress.reduce((s, p) => s + p.watch_time_seconds, 0);

    // Active dates for calendar
    const activeDates = new Set(
      completed.map((p) => new Date(p.completed_at ?? p.created_at).toDateString()),
    );

    // Weekly bar chart: last 8 weeks
    const weeklyData: { week: string; count: number }[] = [];
    const now = Date.now();
    for (let w = 7; w >= 0; w--) {
      const start = now - (w + 1) * 7 * 86400000;
      const end = now - w * 7 * 86400000;
      const weekLabel = new Date(end).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      });
      const count = completed.filter((p) => {
        const t = new Date(p.completed_at ?? p.created_at).getTime();
        return t >= start && t < end;
      }).length;
      weeklyData.push({ week: weekLabel, count });
    }

    // Concept mastery: mock out of completed count
    const masteryScore = Math.min(100, (completed.length / Math.max(progress.length, 1)) * 100);
    const conceptMastery = CONCEPT_AREAS.map((subject, i) => ({
      subject,
      score: Math.round(masteryScore * (0.6 + (i % 3) * 0.15)),
    }));

    return {
      completedCount: completed.length,
      totalCount: progress.length,
      totalMinutes: Math.round(totalTime / 60),
      completionRate:
        progress.length > 0
          ? Math.round((completed.length / progress.length) * 100)
          : 0,
      activeDates,
      weeklyData,
      conceptMastery,
    };
  }, [progress]);

  if (isLoading) {
    return (
      <div className="p-6 md:p-8 max-w-5xl mx-auto space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <Skeleton className="h-48" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Progress</h1>
        <p className="text-muted-foreground text-sm mt-0.5">
          Your learning journey at a glance.
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="flex items-center gap-3 pt-5">
            <div className="rounded-lg bg-primary/10 p-2.5">
              <CheckCircle2 className="h-5 w-5 text-primary" aria-hidden="true" />
            </div>
            <div>
              <p className="text-2xl font-bold leading-none">{stats.completedCount}</p>
              <p className="text-xs text-muted-foreground mt-1">Lessons completed</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 pt-5">
            <div className="rounded-lg bg-primary/10 p-2.5">
              <Clock className="h-5 w-5 text-primary" aria-hidden="true" />
            </div>
            <div>
              <p className="text-2xl font-bold leading-none">{stats.totalMinutes}m</p>
              <p className="text-xs text-muted-foreground mt-1">Time watched</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 pt-5">
            <div className="rounded-lg bg-primary/10 p-2.5">
              <TrendingUp className="h-5 w-5 text-primary" aria-hidden="true" />
            </div>
            <div>
              <p className="text-2xl font-bold leading-none">{stats.completionRate}%</p>
              <p className="text-xs text-muted-foreground mt-1">Completion rate</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Streak calendar */}
      <Card>
        <CardHeader className="pb-3">
          <h2 className="font-semibold text-sm">Activity — Last 52 Weeks</h2>
        </CardHeader>
        <CardContent>
          {stats.activeDates.size > 0 ? (
            <StreakCalendar activeDates={stats.activeDates} />
          ) : (
            <p className="text-sm text-muted-foreground py-4">
              Complete lessons to see your activity calendar.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Weekly bar chart */}
        <Card>
          <CardHeader className="pb-3">
            <h2 className="font-semibold text-sm">Weekly Completions — Last 8 Weeks</h2>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart
                data={stats.weeklyData}
                margin={{ top: 5, right: 5, bottom: 5, left: -25 }}
              >
                <XAxis
                  dataKey="week"
                  tick={{ fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  contentStyle={{
                    borderRadius: "8px",
                    fontSize: "12px",
                    border: "1px solid #27272A",
                    background: "#111111",
                    color: "#FAFAFA",
                  }}
                  formatter={(v) => [`${String(v)} lessons`, "Completed"]}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {stats.weeklyData.map((_, i) => (
                    <Cell key={i} fill="#1D9E75" fillOpacity={0.9} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Concept mastery radar */}
        <Card>
          <CardHeader className="pb-3">
            <h2 className="font-semibold text-sm">Concept Mastery</h2>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={200}>
              <RadarChart data={stats.conceptMastery} margin={{ top: 10, right: 20, bottom: 10, left: 20 }}>
                <PolarGrid stroke="#27272A" />
                <PolarAngleAxis
                  dataKey="subject"
                  tick={{ fontSize: 11, fill: "#A1A1AA" }}
                />
                <Radar
                  name="Mastery"
                  dataKey="score"
                  stroke="#1D9E75"
                  fill="#1D9E75"
                  fillOpacity={0.25}
                />
              </RadarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Lesson completion list */}
      <Card>
        <CardHeader className="pb-3">
          <h2 className="font-semibold text-sm">Lesson History</h2>
        </CardHeader>
        <CardContent className="px-0">
          {progress.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
              <TrendingUp className="h-8 w-8 mx-auto mb-2 opacity-30" aria-hidden="true" />
              <p>No lessons tracked yet. Complete your first lesson!</p>
            </div>
          ) : (
            <div className="divide-y">
              {progress
                .slice()
                .sort(
                  (a, b) =>
                    new Date(b.completed_at ?? b.created_at).getTime() -
                    new Date(a.completed_at ?? a.created_at).getTime(),
                )
                .slice(0, 20)
                .map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center gap-3 px-4 py-3"
                  >
                    <div
                      className={cn(
                        "shrink-0 h-2 w-2 rounded-full",
                        p.status === "completed" ? "bg-primary" : "bg-muted-foreground/40",
                      )}
                      aria-hidden="true"
                    />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {p.status === "completed" ? "Lesson completed" : "In progress"}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {Math.round(p.watch_time_seconds / 60)}m watched
                      </p>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {new Date(p.completed_at ?? p.created_at).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                      })}
                    </span>
                    {p.status === "completed" && (
                      <CheckCircle2
                        className="shrink-0 h-4 w-4 text-primary"
                        aria-hidden="true"
                      />
                    )}
                  </div>
                ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
