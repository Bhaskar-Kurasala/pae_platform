"use client";

import { Activity, Bot, DollarSign, Users } from "lucide-react";
import { useAdminStats } from "@/lib/hooks/use-admin";
import { Card, CardContent } from "@/components/ui/card";

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  color,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ElementType;
  color: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 pt-6">
        <div className={`rounded-xl p-3 ${color}`}>
          <Icon className="h-6 w-6" aria-hidden="true" />
        </div>
        <div>
          <p className="text-2xl font-bold">{value}</p>
          <p className="text-sm text-muted-foreground">{label}</p>
          {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-muted ${className}`} />;
}

export default function AdminOverviewPage() {
  const { data: stats, isLoading } = useAdminStats();

  return (
    <div className="p-6 md:p-8 max-w-6xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Admin Overview</h1>
        <p className="text-muted-foreground mt-1">Platform health at a glance.</p>
      </div>

      {isLoading && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28" />)}
        </div>
      )}

      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Total Students"
            value={stats.total_students.toLocaleString()}
            icon={Users}
            color="bg-primary/10 text-primary"
          />
          <StatCard
            label="MRR"
            value={`$${stats.mrr_usd.toLocaleString()}`}
            sub={`${stats.total_enrollments} enrollments`}
            icon={DollarSign}
            color="bg-[#7C3AED]/10 text-[#7C3AED]"
          />
          <StatCard
            label="Agent Actions"
            value={stats.total_agent_actions.toLocaleString()}
            icon={Bot}
            color="bg-blue-100 text-blue-600"
          />
          <StatCard
            label="Submissions"
            value={stats.total_submissions.toLocaleString()}
            icon={Activity}
            color="bg-green-100 text-green-600"
          />
        </div>
      )}

      {/* Quick nav cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { href: "/admin/agents", title: "Agent Monitor", desc: "View all 20 agents, action counts, error rates" },
          { href: "/admin/students", title: "Students", desc: "Browse enrolled students and engagement scores" },
          { href: "/courses", title: "Courses", desc: "Manage course catalogue and lessons" },
        ].map((item) => (
          <a
            key={item.href}
            href={item.href}
            className="rounded-xl border bg-card p-5 hover:shadow-md transition-shadow group"
          >
            <h3 className="font-semibold group-hover:text-primary transition-colors">{item.title}</h3>
            <p className="text-sm text-muted-foreground mt-1">{item.desc}</p>
          </a>
        ))}
      </div>
    </div>
  );
}
