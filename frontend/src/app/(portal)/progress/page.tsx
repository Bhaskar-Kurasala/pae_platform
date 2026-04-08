"use client";

import { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { CheckCircle2, Clock, TrendingUp } from "lucide-react";
import { useMyProgress } from "@/lib/hooks/use-progress";
import { ProgressBar } from "@/components/features/progress-bar";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export default function ProgressPage() {
  const { data: progress = [], isLoading } = useMyProgress();

  const stats = useMemo(() => {
    const completed = progress.filter((p) => p.status === "completed");
    const totalTime = progress.reduce((s, p) => s + p.watch_time_seconds, 0);
    const byMonth: Record<string, number> = {};
    completed.forEach((p) => {
      const date = new Date(p.completed_at ?? p.created_at);
      const key = date.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
      byMonth[key] = (byMonth[key] ?? 0) + 1;
    });
    return {
      completedCount: completed.length,
      totalCount: progress.length,
      totalMinutes: Math.round(totalTime / 60),
      chartData: Object.entries(byMonth).map(([month, count]) => ({ month, count })),
    };
  }, [progress]);

  if (isLoading) {
    return (
      <div className="p-8 max-w-3xl mx-auto space-y-4 animate-pulse">
        <div className="h-6 bg-muted rounded w-1/3" />
        <div className="h-48 bg-muted rounded-xl" />
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Progress</h1>
        <p className="text-muted-foreground mt-1">Your learning journey at a glance.</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="flex items-center gap-3 pt-6">
            <div className="rounded-lg bg-primary/10 p-2.5">
              <CheckCircle2 className="h-5 w-5 text-primary" aria-hidden="true" />
            </div>
            <div>
              <p className="text-2xl font-bold">{stats.completedCount}</p>
              <p className="text-xs text-muted-foreground">Lessons done</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 pt-6">
            <div className="rounded-lg bg-primary/10 p-2.5">
              <Clock className="h-5 w-5 text-primary" aria-hidden="true" />
            </div>
            <div>
              <p className="text-2xl font-bold">{stats.totalMinutes}m</p>
              <p className="text-xs text-muted-foreground">Time watched</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 pt-6">
            <div className="rounded-lg bg-primary/10 p-2.5">
              <TrendingUp className="h-5 w-5 text-primary" aria-hidden="true" />
            </div>
            <div>
              <p className="text-2xl font-bold">
                {stats.totalCount > 0
                  ? Math.round((stats.completedCount / stats.totalCount) * 100)
                  : 0}
                %
              </p>
              <p className="text-xs text-muted-foreground">Completion rate</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Completion bar */}
      <Card>
        <CardHeader className="pb-2">
          <h2 className="font-semibold">Overall Progress</h2>
        </CardHeader>
        <CardContent>
          <ProgressBar
            value={
              stats.totalCount > 0
                ? (stats.completedCount / stats.totalCount) * 100
                : 0
            }
            label={`${stats.completedCount} / ${stats.totalCount} lessons`}
          />
        </CardContent>
      </Card>

      {/* Monthly chart */}
      {stats.chartData.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <h2 className="font-semibold">Lessons Completed by Month</h2>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={stats.chartData} margin={{ top: 5, right: 5, bottom: 5, left: -20 }}>
                <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip
                  contentStyle={{ borderRadius: "8px", fontSize: "12px" }}
                  formatter={(v) => [`${String(v)} lessons`, "Completed"]}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {stats.chartData.map((_, i) => (
                    <Cell key={i} fill="#1D9E75" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {progress.length === 0 && (
        <div className="rounded-xl border border-dashed p-12 text-center text-muted-foreground">
          <TrendingUp className="h-10 w-10 mx-auto mb-3 opacity-30" aria-hidden="true" />
          <p>No progress tracked yet. Complete your first lesson to see stats here.</p>
        </div>
      )}
    </div>
  );
}
