"use client";

import { Activity, MessageSquare, RefreshCw, TrendingUp, Users, Zap } from "lucide-react";
import { useAdminPulse } from "@/lib/hooks/use-admin";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  label: string;
  value: string | number;
  icon: LucideIcon;
  accent: string;
}

function StatCard({ label, value, icon: Icon, accent }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-xs font-medium text-muted-foreground">{label}</CardTitle>
        <Icon className={cn("h-4 w-4", accent)} aria-hidden="true" />
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-bold">{value}</p>
      </CardContent>
    </Card>
  );
}

function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-xl border bg-card p-4">
      <div className="mb-3 h-3 w-24 rounded bg-muted" />
      <div className="h-8 w-16 rounded bg-muted" />
    </div>
  );
}

export default function PulsePage() {
  const { data, isLoading, refetch } = useAdminPulse();

  const stats: StatCardProps[] = data
    ? [
        {
          label: "Active students (24h)",
          value: data.active_students_24h,
          icon: Users,
          accent: "text-primary",
        },
        {
          label: "Agent calls (24h)",
          value: data.agent_calls_24h,
          icon: Zap,
          accent: "text-amber-500",
        },
        {
          label: "Avg eval score (24h)",
          value: `${(data.avg_eval_score_24h * 100).toFixed(0)}%`,
          icon: Activity,
          accent: "text-green-500",
        },
        {
          label: "New enrollments (7d)",
          value: data.new_enrollments_7d,
          icon: TrendingUp,
          accent: "text-blue-500",
        },
        {
          label: "Open feedback",
          value: data.open_feedback,
          icon: MessageSquare,
          accent:
            data.open_feedback > 0
              ? "text-destructive"
              : "text-muted-foreground",
        },
      ]
    : [];

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Platform Pulse</h1>
        <button
          onClick={() => void refetch()}
          aria-label="Refresh pulse data"
          className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {isLoading
          ? [1, 2, 3, 4, 5].map((n) => <SkeletonCard key={n} />)
          : stats.map((s) => (
              <StatCard
                key={s.label}
                label={s.label}
                value={s.value}
                icon={s.icon}
                accent={s.accent}
              />
            ))}
      </div>
    </div>
  );
}
