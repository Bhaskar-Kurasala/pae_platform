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
