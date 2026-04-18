"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

export interface AdminStats {
  total_students: number;
  total_enrollments: number;
  total_submissions: number;
  total_agent_actions: number;
  mrr_cents: number;
  mrr_usd: number;
}

export interface AgentHealth {
  name: string;
  description: string;
  total_actions: number;
  error_count: number;
  avg_duration_ms: number;
  status: "healthy" | "degraded";
}

export interface AdminStudent {
  id: string;
  email: string;
  full_name: string;
  created_at: string;
  last_login_at: string | null;
  lessons_completed: number;
  agent_interactions: number;
  is_active: boolean;
}

export function useAdminStats() {
  return useQuery<AdminStats>({
    queryKey: ["admin", "stats"],
    queryFn: () => api.get<AdminStats>("/api/v1/admin/stats"),
  });
}

export function useAgentsHealth() {
  return useQuery<AgentHealth[]>({
    queryKey: ["admin", "agents", "health"],
    queryFn: () => api.get<AgentHealth[]>("/api/v1/admin/agents/health"),
    refetchInterval: 30_000,
  });
}

export function useAdminStudents() {
  return useQuery<AdminStudent[]>({
    queryKey: ["admin", "students"],
    queryFn: () => api.get<AdminStudent[]>("/api/v1/admin/students"),
  });
}

// ── Confusion heatmap (P2-13) ──────────────────────────────────────
export interface ConfusionBucket {
  topic: string;
  help_count: number;
  distinct_students: number;
  last_seen: string | null;
  score: number;
  sample_questions: string[];
}

export function useConfusionHeatmap(days: number = 30) {
  return useQuery<ConfusionBucket[]>({
    queryKey: ["admin", "confusion-heatmap", days],
    queryFn: () =>
      api.get<ConfusionBucket[]>(
        `/api/v1/admin/confusion-heatmap?days=${days}&limit=20`,
      ),
    staleTime: 60_000,
  });
}

// ── At-risk student list (P2-14) ──────────────────────────────────
export interface AtRiskSignal {
  name: string;
  weight: number;
  reason: string;
}

export interface AtRiskStudent {
  student_id: string;
  email: string;
  full_name: string;
  risk_score: number;
  reasons: string[];
  no_login_days: number | null;
  lesson_stall_days: number | null;
  help_requests_recent: number;
  help_requests_prior: number;
  low_mood_count: number;
  progress_pct: number;
  signals: AtRiskSignal[];
}

export function useAtRiskStudents(minScore: number = 0.35) {
  return useQuery<AtRiskStudent[]>({
    queryKey: ["admin", "at-risk-students", minScore],
    queryFn: () =>
      api.get<AtRiskStudent[]>(
        `/api/v1/admin/at-risk-students?min_score=${minScore}&limit=50`,
      ),
    staleTime: 60_000,
  });
}
