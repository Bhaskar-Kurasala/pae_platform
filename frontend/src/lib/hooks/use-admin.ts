"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  last_called_at: string | null;
  success_rate: number | null;
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

export interface StudentTimelineEvent {
  kind: "login" | "lesson_completed" | "agent_action" | "submission";
  at: string;
  summary: string;
  detail: Record<string, unknown> | null;
}

export interface TriggerAgentResponse {
  agent_name: string;
  status: string;
  duration_ms: number;
  response_preview: string;
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

export function useAdminStudents(search: string = "") {
  // DISC-56 — push the filter to the backend when the user types something;
  // `q` is null-safe there, so an empty string falls back to the unfiltered
  // list. React Query keys on `search` so each query is cached independently.
  const params = search.trim() ? `?q=${encodeURIComponent(search.trim())}` : "";
  return useQuery<AdminStudent[]>({
    queryKey: ["admin", "students", search.trim()],
    queryFn: () => api.get<AdminStudent[]>(`/api/v1/admin/students${params}`),
  });
}

export function useStudentTimeline(studentId: string | null | undefined) {
  return useQuery<StudentTimelineEvent[]>({
    queryKey: ["admin", "students", studentId, "timeline"],
    queryFn: () =>
      api.get<StudentTimelineEvent[]>(
        `/api/v1/admin/students/${studentId}/timeline`,
      ),
    enabled: !!studentId,
  });
}

export function useTriggerAgent() {
  const queryClient = useQueryClient();
  return useMutation<
    TriggerAgentResponse,
    Error,
    { agentName: string; studentId: string; task?: string }
  >({
    mutationFn: ({ agentName, studentId, task }) =>
      api.post<TriggerAgentResponse>(
        `/api/v1/admin/agents/${agentName}/trigger`,
        { student_id: studentId, task },
      ),
    onSuccess: (_res, vars) => {
      void queryClient.invalidateQueries({
        queryKey: ["admin", "students", vars.studentId, "timeline"],
      });
      void queryClient.invalidateQueries({ queryKey: ["admin", "agents", "health"] });
    },
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

// ── Feedback triage (#177) ────────────────────────────────────────
export interface FeedbackItem {
  id: string;
  user_id: string | null;
  route: string;
  body: string;
  sentiment: string | null;
  resolved: boolean;
  created_at: string;
}

export function useAdminFeedback() {
  return useQuery<FeedbackItem[]>({
    queryKey: ["admin", "feedback"],
    queryFn: () => api.get<FeedbackItem[]>("/api/v1/feedback/admin"),
    staleTime: 30_000,
  });
}

export function useResolveFeedback() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id: string) => api.patch<void>(`/api/v1/feedback/admin/${id}/resolve`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "feedback"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "pulse"] });
    },
  });
}

// ── Pulse dashboard (#180) ─────────────────────────────────────────
export interface PulseData {
  active_students_24h: number;
  agent_calls_24h: number;
  avg_eval_score_24h: number;
  new_enrollments_7d: number;
  open_feedback: number;
}

export function useAdminPulse() {
  return useQuery<PulseData>({
    queryKey: ["admin", "pulse"],
    queryFn: () => api.get<PulseData>("/api/v1/admin/pulse"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

// ── F2 — Student notes (admin's private record per student) ────────
// The backend routes already exist (POST + GET /admin/students/{id}/notes)
// from Phase 3; F2 only adds the frontend wiring so admins can actually
// see + write notes. Append-only by convention.

export interface StudentNote {
  id: string;
  admin_id: string;
  student_id: string;
  body_md: string;
  created_at: string;
  updated_at: string;
}

export function useStudentNotes(studentId: string | null | undefined) {
  return useQuery<StudentNote[]>({
    queryKey: ["admin", "student-notes", studentId],
    queryFn: () =>
      api.get<StudentNote[]>(
        `/api/v1/admin/students/${studentId}/notes?limit=50`,
      ),
    enabled: !!studentId,
    staleTime: 30_000,
  });
}

export function useCreateStudentNote(studentId: string | null | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body_md: string) =>
      api.post<StudentNote>(
        `/api/v1/admin/students/${studentId}/notes`,
        { body_md },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["admin", "student-notes", studentId],
      });
    },
  });
}

// ── F4 — Retention engine panels ────────────────────────────────────
// Reads from /admin/risk-panels which queries student_risk_signals
// (populated nightly by F1's risk-scoring task). Each panel is one
// slip pattern; the dashboard renders them in priority order.

export interface RiskPanelStudent {
  user_id: string;
  name: string;
  email: string;
  risk_score: number;
  risk_reason: string | null;
  days_since_last_session: number | null;
  max_streak_ever: number;
  paid: boolean;
  recommended_intervention: string | null;
}

export interface RiskPanel {
  students: RiskPanelStudent[];
  total: number;
}

export type RiskPanels = {
  paid_silent: RiskPanel;
  capstone_stalled: RiskPanel;
  streak_broken: RiskPanel;
  promotion_avoidant: RiskPanel;
  cold_signup: RiskPanel;
};

export function useRiskPanels() {
  return useQuery<RiskPanels>({
    queryKey: ["admin", "risk-panels"],
    queryFn: () => api.get<RiskPanels>("/api/v1/admin/risk-panels"),
    // Panels recompute nightly via Celery; a 1-hour staleness is fine.
    // Manual refresh on the page covers the "I just ran the task" case.
    staleTime: 60 * 60_000,
  });
}

// ── F11 — Refund offer flow ─────────────────────────────────────────
// Surfaced on /admin/students/{id} when the student's risk panel
// position is paid_silent. POST proposes + sends in one step.

export interface RefundOffer {
  id: string;
  user_id: string;
  proposed_by: string | null;
  status: "proposed" | "sent" | "accepted" | "declined" | "expired" | string;
  reason: string | null;
  outreach_log_id: string | null;
  proposed_at: string;
  responded_at: string | null;
}

export function useRefundOffers(studentId: string | null) {
  return useQuery<RefundOffer[]>({
    queryKey: ["admin", "refund-offers", studentId],
    enabled: !!studentId,
    queryFn: () =>
      api.get<RefundOffer[]>(
        `/api/v1/admin/students/${studentId}/refund-offers`,
      ),
  });
}

export function useSendRefundOffer(studentId: string | null) {
  const queryClient = useQueryClient();
  return useMutation<RefundOffer, Error, { reason: string | null }>({
    mutationFn: ({ reason }) =>
      api.post<RefundOffer>(
        `/api/v1/admin/students/${studentId}/refund-offer`,
        { reason },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["admin", "refund-offers", studentId],
      });
    },
  });
}
