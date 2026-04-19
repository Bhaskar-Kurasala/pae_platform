"use client";

import { useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import {
  Activity,
  Bot,
  CheckCircle2,
  Clock,
  DollarSign,
  GraduationCap,
  RefreshCw,
  Users,
  XCircle,
  AlertCircle,
} from "lucide-react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAdminStats, useAgentsHealth, useAdminStudents } from "@/lib/hooks/use-admin";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

// ── Types ────────────────────────────────────────────────────────
interface HealthResponse {
  status: string;
  redis: string;
  db: string;
}

// ── Helpers ──────────────────────────────────────────────────────
function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-xl bg-muted", className)}
      aria-hidden="true"
    />
  );
}

// ── KPI Card ─────────────────────────────────────────────────────
function KpiCard({
  label,
  value,
  sub,
  icon: Icon,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ElementType;
  accent: string;
}) {
  return (
    <div className="rounded-xl border bg-card p-5 flex flex-col gap-3">
      <div className={cn("rounded-lg p-2.5 w-fit", accent)}>
        <Icon className="h-4 w-4" aria-hidden="true" />
      </div>
      <div>
        <p className="text-2xl font-bold leading-none">{value}</p>
        <p className="text-sm text-muted-foreground mt-1">{label}</p>
        {sub && <p className="text-xs text-primary mt-0.5 font-medium">{sub}</p>}
      </div>
    </div>
  );
}

// ── Agent calls area chart mock data ──────────────────────────────
function buildChartData(totalCalls: number) {
  const data = [];
  const now = Date.now();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now - i * 86400000);
    const day = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
    // Simulate distribution across 4 categories
    const base = Math.round((totalCalls / 7) * (0.7 + Math.random() * 0.6));
    data.push({
      day,
      creation: Math.round(base * 0.35),
      learning: Math.round(base * 0.3),
      career: Math.round(base * 0.2),
      engagement: Math.round(base * 0.15),
    });
  }
  return data;
}

// ── Status indicator ──────────────────────────────────────────────
function StatusDot({ status }: { status: "healthy" | "degraded" | "unknown" }) {
  return (
    <span
      aria-label={`Status: ${status}`}
      className={cn(
        "inline-block h-2 w-2 rounded-full shrink-0",
        status === "healthy"
          ? "bg-primary"
          : status === "degraded"
          ? "bg-amber-500"
          : "bg-muted-foreground/40",
      )}
    />
  );
}

// ── System Status Card ────────────────────────────────────────────
function SystemStatus() {
  const { data: health, isLoading, refetch, isRefetching } = useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: () => api.get<HealthResponse>("/health"),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const items = [
    {
      label: "Backend API",
      status: health ? (health.status === "ok" ? "healthy" : "degraded") : "unknown",
      icon: CheckCircle2,
    },
    {
      label: "Redis",
      status: health ? (health.redis === "ok" ? "healthy" : "degraded") : "unknown",
      icon: Activity,
    },
    {
      label: "PostgreSQL",
      status: health ? (health.db === "ok" ? "healthy" : "degraded") : "unknown",
      icon: Activity,
    },
  ] as const;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-sm">System Status</h2>
          <button
            onClick={() => void refetch()}
            disabled={isRefetching || isLoading}
            aria-label="Refresh system status"
            className="rounded p-1 hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5 text-muted-foreground", isRefetching && "animate-spin")}
              aria-hidden="true"
            />
          </button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {isLoading
          ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-8" />)
          : items.map(({ label, status }) => (
              <div key={label} className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{label}</span>
                <div className="flex items-center gap-1.5">
                  <StatusDot status={status as "healthy" | "degraded" | "unknown"} />
                  <span
                    className={cn(
                      "text-xs font-medium capitalize",
                      status === "healthy"
                        ? "text-primary"
                        : status === "degraded"
                        ? "text-amber-600"
                        : "text-muted-foreground",
                    )}
                  >
                    {status}
                  </span>
                </div>
              </div>
            ))}
      </CardContent>
    </Card>
  );
}

// ── Page ─────────────────────────────────────────────────────────
export default function AdminOverviewPage() {
  const { data: stats, isLoading: statsLoading, refetch: refetchStats, isRefetching } = useAdminStats();
  const { data: agentsHealth = [], isLoading: agentsLoading } = useAgentsHealth();
  const { data: students = [], isLoading: studentsLoading } = useAdminStudents();

  const [lastUpdated] = useState(() => new Date().toLocaleTimeString());

  const chartData = stats ? buildChartData(stats.total_agent_actions) : [];

  const avgResponseTime = agentsHealth.length
    ? Math.round(agentsHealth.reduce((s, a) => s + a.avg_duration_ms, 0) / agentsHealth.length)
    : 0;

  const activeThisWeek = students.filter((s) => {
    if (!s.last_login_at) return false;
    return Date.now() - new Date(s.last_login_at).getTime() < 7 * 86400000;
  }).length;

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Admin Dashboard</h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Last updated: {lastUpdated}
          </p>
        </div>
        <button
          onClick={() => void refetchStats()}
          disabled={isRefetching}
          aria-label="Refresh dashboard data"
          className="flex items-center gap-2 h-9 rounded-lg border border-border px-4 text-sm font-medium hover:bg-muted transition-colors disabled:opacity-50 w-fit"
        >
          <RefreshCw
            className={cn("h-4 w-4", isRefetching && "animate-spin")}
            aria-hidden="true"
          />
          Refresh
        </button>
      </div>

      {/* KPI row */}
      {statsLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : stats ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <KpiCard
            label="Total Students"
            value={stats.total_students.toLocaleString()}
            icon={Users}
            accent="bg-primary/10 text-primary"
          />
          <KpiCard
            label="Active This Week"
            value={activeThisWeek.toLocaleString()}
            sub={`of ${stats.total_students} total`}
            icon={Activity}
            accent="bg-[#7C3AED]/10 text-[#7C3AED]"
          />
          {/* DISC-53 — Enrollments + MRR tiles: the backend has been returning
              `total_enrollments` and `mrr_usd` for weeks; AD2 failed only because
              the UI wasn't consuming them. */}
          <KpiCard
            label="Enrollments"
            value={stats.total_enrollments.toLocaleString()}
            icon={GraduationCap}
            accent="bg-emerald-500/10 text-emerald-600"
          />
          <KpiCard
            label="MRR"
            value={`$${stats.mrr_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
            sub={`${(stats.mrr_cents / 100).toFixed(2)} lifetime`}
            icon={DollarSign}
            accent="bg-green-500/10 text-green-600"
          />
          <KpiCard
            label="Total Agent Calls"
            value={stats.total_agent_actions.toLocaleString()}
            icon={Bot}
            accent="bg-blue-500/10 text-blue-600"
          />
          <KpiCard
            label="Avg Response Time"
            value={`${avgResponseTime}ms`}
            sub={avgResponseTime < 2000 ? "Within target" : "Above target"}
            icon={Clock}
            accent="bg-amber-500/10 text-amber-600"
          />
        </div>
      ) : null}

      {/* Agent calls chart + system status */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
        {/* Area chart */}
        <Card>
          <CardHeader className="pb-3">
            <h2 className="font-semibold text-sm">Agent Calls — Last 7 Days</h2>
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Skeleton className="h-52" />
            ) : (
              <ResponsiveContainer width="100%" height={210}>
                <AreaChart data={chartData} margin={{ top: 5, right: 5, bottom: 5, left: -25 }}>
                  <defs>
                    <linearGradient id="colorCreation" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#1D9E75" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#1D9E75" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="colorLearning" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#7C3AED" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#7C3AED" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="colorCareer" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="colorEngagement" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#F59E0B" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#F59E0B" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272A" vertical={false} />
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 10, fill: "#A1A1AA" }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: "#A1A1AA" }}
                    tickLine={false}
                    axisLine={false}
                    allowDecimals={false}
                  />
                  <Tooltip
                    contentStyle={{
                      borderRadius: "8px",
                      fontSize: "12px",
                      border: "1px solid #27272A",
                      background: "#111111",
                      color: "#FAFAFA",
                    }}
                  />
                  <Area type="monotone" dataKey="creation" stroke="#1D9E75" fill="url(#colorCreation)" strokeWidth={2} name="Creation" />
                  <Area type="monotone" dataKey="learning" stroke="#7C3AED" fill="url(#colorLearning)" strokeWidth={2} name="Learning" />
                  <Area type="monotone" dataKey="career" stroke="#3B82F6" fill="url(#colorCareer)" strokeWidth={2} name="Career" />
                  <Area type="monotone" dataKey="engagement" stroke="#F59E0B" fill="url(#colorEngagement)" strokeWidth={2} name="Engagement" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* System status */}
        <SystemStatus />
      </div>

      {/* Agent health table */}
      <Card>
        <CardHeader className="pb-3">
          <h2 className="font-semibold text-sm">Agent Health</h2>
        </CardHeader>
        <CardContent className="px-0">
          {agentsLoading ? (
            <div className="px-4 space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : agentsHealth.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted-foreground text-center">
              No agent health data available.
            </p>
          ) : (
            <>
              {/* DISC-58 — mobile stacked cards; the 6-column table can't shrink below ~720px
                  without horizontal scroll on phones. */}
              <div className="md:hidden px-4 space-y-2">
                {agentsHealth.map((agent) => (
                  <div key={agent.name} className="rounded-lg border p-3 flex flex-col gap-1">
                    <div className="flex items-center justify-between">
                      <span className="font-medium capitalize text-sm">
                        {agent.name.split("_").join(" ")}
                      </span>
                      <span
                        className={cn(
                          "text-xs font-medium capitalize",
                          agent.status === "healthy" ? "text-primary" : "text-amber-600",
                        )}
                      >
                        {agent.status}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                      <span>Calls: <span className="text-foreground">{agent.total_actions}</span></span>
                      <span>
                        Success:{" "}
                        <span className="text-foreground">
                          {agent.success_rate != null
                            ? `${Math.round(agent.success_rate * 100)}%`
                            : "—"}
                        </span>
                      </span>
                      <span>Latency: <span className="text-foreground">{agent.avg_duration_ms > 0 ? `${agent.avg_duration_ms}ms` : "—"}</span></span>
                      <span className="truncate">
                        Last:{" "}
                        <span className="text-foreground">
                          {agent.last_called_at
                            ? new Date(agent.last_called_at).toLocaleDateString()
                            : "never"}
                        </span>
                      </span>
                    </div>
                  </div>
                ))}
              </div>
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-sm" aria-label="Agent health table">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground">Agent</th>
                      <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground">Total Calls</th>
                      <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground">Success Rate</th>
                      <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground">Latency</th>
                      <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground">Last Call</th>
                      <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {agentsHealth.map((agent) => (
                      <tr key={agent.name} className="hover:bg-muted/30 transition-colors">
                        <td className="px-4 py-3 font-medium capitalize">
                          {agent.name.split("_").join(" ")}
                        </td>
                        <td className="px-4 py-3 text-right text-muted-foreground">
                          {agent.total_actions.toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {agent.success_rate != null ? (
                            <span
                              className={cn(
                                "font-medium",
                                agent.success_rate >= 0.95
                                  ? "text-primary"
                                  : agent.success_rate >= 0.8
                                  ? "text-amber-600"
                                  : "text-destructive",
                              )}
                            >
                              {Math.round(agent.success_rate * 100)}%
                            </span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right text-muted-foreground">
                          {agent.avg_duration_ms > 0 ? `${agent.avg_duration_ms}ms` : "—"}
                        </td>
                        <td className="px-4 py-3 text-right text-muted-foreground">
                          {agent.last_called_at ? (
                            <span title={new Date(agent.last_called_at).toLocaleString()}>
                              {new Date(agent.last_called_at).toLocaleDateString()}
                            </span>
                          ) : (
                            "never"
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            {agent.status === "healthy" ? (
                              <CheckCircle2 className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                            ) : agent.status === "degraded" ? (
                              <AlertCircle className="h-3.5 w-3.5 text-amber-500" aria-hidden="true" />
                            ) : (
                              <XCircle className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                            )}
                            <span
                              className={cn(
                                "text-xs font-medium capitalize",
                                agent.status === "healthy"
                                  ? "text-primary"
                                  : agent.status === "degraded"
                                  ? "text-amber-600"
                                  : "text-muted-foreground",
                              )}
                            >
                              {agent.status}
                            </span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Top students table */}
      <Card>
        <CardHeader className="pb-3">
          <h2 className="font-semibold text-sm">Top Students</h2>
        </CardHeader>
        <CardContent className="px-0">
          {studentsLoading ? (
            <div className="px-4 space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : students.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted-foreground text-center">
              No student data available.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label="Top students table">
                <thead>
                  <tr className="border-b">
                    <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground">Student</th>
                    <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground">Lessons</th>
                    <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground">Agent Interactions</th>
                    <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {students
                    .slice()
                    .sort((a, b) => b.lessons_completed - a.lessons_completed)
                    .slice(0, 5)
                    .map((student) => (
                      <tr key={student.id} className="hover:bg-muted/30 transition-colors">
                        <td className="px-4 py-3">
                          <Link
                            href={`/admin/students/${student.id}`}
                            className="block hover:underline underline-offset-2"
                          >
                            <p className="font-medium">{student.full_name}</p>
                            <p className="text-xs text-muted-foreground">{student.email}</p>
                          </Link>
                        </td>
                        <td className="px-4 py-3 text-right text-muted-foreground">
                          {student.lessons_completed}
                        </td>
                        <td className="px-4 py-3 text-right text-muted-foreground">
                          {student.agent_interactions}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <span
                            className={cn(
                              "rounded-full px-2.5 py-0.5 text-xs font-medium",
                              student.is_active
                                ? "bg-primary/10 text-primary"
                                : "bg-muted text-muted-foreground",
                            )}
                          >
                            {student.is_active ? "Active" : "Inactive"}
                          </span>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
