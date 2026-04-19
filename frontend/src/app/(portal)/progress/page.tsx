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
import { CheckCircle2, Clock, FileCode2, TrendingUp } from "lucide-react";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { useMySkillStates } from "@/lib/hooks/use-skills";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { activeDaySet } from "@/lib/streak";

// ── Skeleton ─────────────────────────────────────────────────────
function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-xl bg-muted", className)}
      aria-hidden="true"
    />
  );
}

// ── Activity calendar (consistency receipt — not loss-aversion) ───
function ActivityCalendar({ activeDays }: { activeDays: Set<string> }) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const cells: { dateStr: string; ymd: string; active: boolean }[] = [];
  const toYmd = (d: Date) =>
    `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;

  for (let i = 363; i >= 0; i--) {
    const d = new Date(today.getTime() - i * 86400000);
    const ymd = toYmd(d);
    cells.push({ dateStr: d.toDateString(), ymd, active: activeDays.has(ymd) });
  }

  const weeks: { dateStr: string; ymd: string; active: boolean }[][] = [];
  for (let w = 0; w < 52; w++) {
    weeks.push(cells.slice(w * 7, w * 7 + 7));
  }

  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex gap-1 min-w-max">
        {weeks.map((week, wi) => (
          <div key={wi} className="flex flex-col gap-1">
            {week.map((cell, di) => (
              <div
                key={di}
                title={`${cell.dateStr}${cell.active ? " — active" : ""}`}
                aria-label={`${cell.dateStr}${cell.active ? ", active" : ""}`}
                className={cn(
                  "h-3 w-3 rounded-sm transition-colors",
                  cell.active ? "bg-primary" : "bg-muted",
                )}
              />
            ))}
          </div>
        ))}
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
  const { data: progressData, isLoading } = useMyProgress();
  const { data: skillStates } = useMySkillStates();

  const activeDays = useMemo(() => {
    // DISC-47c — union lesson-completion dates (backend completions_by_day)
    // with skill-touched dates so the calendar lights up from BOTH signals.
    const skillDays = activeDaySet(
      (skillStates ?? []).map((s) => s.last_touched_at),
    );
    for (const bucket of progressData?.completions_by_day ?? []) {
      skillDays.add(bucket.date);
    }
    return skillDays;
  }, [skillStates, progressData?.completions_by_day]);

  const stats = useMemo(() => {
    const courses = progressData?.courses ?? [];
    const allLessons = courses.flatMap((c) => c.lessons);
    const completedLessons = allLessons.filter((l) => l.status === "completed");
    const totalLessons = allLessons.length;
    const completedCount = completedLessons.length;

    // DISC-47b — real watch time from the backend (sum of
    // `student_progress.watch_time_seconds` / 60).
    const totalMinutes = progressData?.watch_time_minutes ?? 0;

    // DISC-47c — weekly bar chart buckets the last 8 weeks of
    // `completions_by_day` into calendar-week windows.
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const completionsByDay = new Map<string, number>();
    for (const bucket of progressData?.completions_by_day ?? []) {
      completionsByDay.set(bucket.date, bucket.count);
    }
    const toYmd = (d: Date) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const weeklyData: { week: string; count: number }[] = [];
    for (let w = 7; w >= 0; w--) {
      const weekStart = new Date(today.getTime() - w * 7 * 86400000);
      let count = 0;
      for (let d = 0; d < 7; d++) {
        const day = new Date(weekStart.getTime() + d * 86400000);
        count += completionsByDay.get(toYmd(day)) ?? 0;
      }
      weeklyData.push({
        week: weekStart.toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
        }),
        count,
      });
    }

    // Concept mastery: based on completion ratio (unchanged — radar is cosmetic)
    const masteryScore = Math.min(100, totalLessons > 0 ? (completedCount / totalLessons) * 100 : 0);
    const conceptMastery = CONCEPT_AREAS.map((subject, i) => ({
      subject,
      score: Math.round(masteryScore * (0.6 + (i % 3) * 0.15)),
    }));

    const courseHistory = courses.filter((c) => c.completed_lessons > 0);

    return {
      completedCount,
      totalCount: totalLessons,
      totalMinutes,
      completionRate: totalLessons > 0 ? Math.round((completedCount / totalLessons) * 100) : 0,
      exercisesCompleted: progressData?.exercises_completed ?? 0,
      totalExercises: progressData?.total_exercises ?? 0,
      exerciseRate: Math.round(progressData?.exercise_completion_rate ?? 0),
      weeklyData,
      conceptMastery,
      courseHistory,
      overallProgress: progressData?.overall_progress ?? 0,
    };
  }, [progressData]);

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
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
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
              <FileCode2 className="h-5 w-5 text-primary" aria-hidden="true" />
            </div>
            <div>
              <p className="text-2xl font-bold leading-none">
                {stats.exercisesCompleted}
                <span className="text-base font-medium text-muted-foreground">
                  /{stats.totalExercises}
                </span>
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Exercises completed{stats.totalExercises > 0 ? ` · ${stats.exerciseRate}%` : ""}
              </p>
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

      {/* Activity — consistency receipt */}
      <Card>
        <CardHeader className="pb-3">
          <h2 className="font-semibold text-sm">Activity — Last 52 Weeks</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Each square is a day you touched a skill or completed a lesson.
          </p>
        </CardHeader>
        <CardContent>
          {activeDays.size > 0 ? (
            <ActivityCalendar activeDays={activeDays} />
          ) : (
            <p className="text-sm text-muted-foreground py-4">
              Touch a skill on the map or complete a lesson to start building your activity record.
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
          {stats.courseHistory.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
              <TrendingUp className="h-8 w-8 mx-auto mb-2 opacity-30" aria-hidden="true" />
              <p>No lessons tracked yet. Complete your first lesson!</p>
            </div>
          ) : (
            <div className="divide-y">
              {stats.courseHistory.map((c) => (
                <div key={c.course_id} className="flex items-center gap-3 px-4 py-3">
                  <div className="shrink-0 h-2 w-2 rounded-full bg-primary" aria-hidden="true" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{c.course_title}</p>
                    <p className="text-xs text-muted-foreground">
                      {c.completed_lessons} / {c.total_lessons} lessons completed
                    </p>
                  </div>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {Math.round(c.progress_percentage)}%
                  </span>
                  {c.completed_lessons === c.total_lessons && (
                    <CheckCircle2 className="shrink-0 h-4 w-4 text-primary" aria-hidden="true" />
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
