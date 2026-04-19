"use client";

import { AlertCircle, Bot, CheckCircle2, Clock } from "lucide-react";
import { useAgentsHealth } from "@/lib/hooks/use-admin";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

function Skeleton() {
  return <div className="h-24 animate-pulse rounded-xl bg-muted" />;
}

export default function AgentMonitorPage() {
  const { data: agents, isLoading } = useAgentsHealth();

  return (
    <div className="p-6 md:p-8 max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Agent Monitor</h1>
        <p className="text-muted-foreground mt-1">
          All registered agents, action counts, and health status. Auto-refreshes every 30s.
        </p>
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {Array.from({ length: 10 }).map((_, i) => <Skeleton key={i} />)}
        </div>
      )}

      {agents && agents.length === 0 && (
        <div className="text-center py-16 text-muted-foreground">
          No agent data yet. API server may not be running.
        </div>
      )}

      {agents && agents.length > 0 && (
        <>
          <div className="flex items-center gap-4 mb-6 text-sm">
            <span className="flex items-center gap-1 text-green-600">
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              {agents.filter((a) => a.status === "healthy").length} healthy
            </span>
            <span className="flex items-center gap-1 text-yellow-600">
              <AlertCircle className="h-4 w-4" aria-hidden="true" />
              {agents.filter((a) => a.status === "degraded").length} degraded
            </span>
            <span className="text-muted-foreground ml-auto">{agents.length} total agents</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {agents.map((agent) => (
              <Card key={agent.name} className="hover:shadow-sm transition-shadow">
                <CardHeader className="pb-2 pt-4 px-5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Bot className="h-4 w-4 text-primary shrink-0" aria-hidden="true" />
                      <h3 className="font-medium text-sm">{agent.name}</h3>
                    </div>
                    <Badge
                      className={
                        agent.status === "healthy"
                          ? "bg-green-100 text-green-700 hover:bg-green-100"
                          : "bg-yellow-100 text-yellow-700 hover:bg-yellow-100"
                      }
                    >
                      {agent.status}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">
                    {agent.description}
                  </p>
                </CardHeader>
                <CardContent className="px-5 pb-4">
                  <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Activity className="h-3 w-3" aria-hidden="true" />
                      {agent.total_actions} actions
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" aria-hidden="true" />
                      {agent.avg_duration_ms}ms avg
                    </span>
                    {/* DISC-54 — surface success_rate + last_called_at */}
                    {agent.success_rate != null && (
                      <span className="flex items-center gap-1">
                        <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                        {Math.round(agent.success_rate * 100)}% success
                      </span>
                    )}
                    <span className="text-muted-foreground/80">
                      Last: {agent.last_called_at
                        ? new Date(agent.last_called_at).toLocaleDateString()
                        : "never"}
                    </span>
                    {agent.error_count > 0 && (
                      <span className="flex items-center gap-1 text-destructive">
                        <AlertCircle className="h-3 w-3" aria-hidden="true" />
                        {agent.error_count} errors
                      </span>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Activity({ className = "", ...props }: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      {...props}
    >
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  );
}
