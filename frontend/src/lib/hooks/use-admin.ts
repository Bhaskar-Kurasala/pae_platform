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
  // D16/CP3.2 — when set, cockpit renders the wa.me deep link button
  // on the per-student panel.
  whatsapp_number?: string | null;
}

export interface StudentTimelineEvent {
  // D16/CP3.3 — "outreach" added so WhatsApp/phone/email/in_app
  // contacts surface alongside agent actions. detail.channel carries
  // the channel value so the frontend renders the right badge.
  kind: "login" | "lesson_completed" | "agent_action" | "submission" | "outreach";
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

export type AdminStudentSort =
  | "joined_asc"
  | "joined_desc"
  | "name_asc"
  | "name_desc"
  | "last_seen_asc"
  | "last_seen_desc";

export type SlipType =
  | "paid_silent"
  | "capstone_stalled"
  | "streak_broken"
  | "promotion_avoidant"
  | "cold_signup"
  | "unpaid_stalled";

export function useAdminStudents(
  search: string = "",
  sort: AdminStudentSort = "joined_desc",
  slipType: SlipType | null = null,
) {
  // DISC-56 — push the filter to the backend when the user types something.
  // F13 — sort param goes through the same query string.
  // Retention deep-link — slip_type filters to students whose F1
  // pattern matches, so the panel "See all N →" link lands on the
  // roster pre-filtered to that slip pattern.
  const sp = new URLSearchParams();
  if (search.trim()) sp.set("q", search.trim());
  if (sort !== "joined_desc") sp.set("sort", sort);
  if (slipType) sp.set("slip_type", slipType);
  const qs = sp.toString();
  const params = qs ? `?${qs}` : "";
  return useQuery<AdminStudent[]>({
    queryKey: ["admin", "students", search.trim(), sort, slipType],
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

// F14 — fetch the next page of older timeline events. Caller passes the
// `at` of the oldest event currently rendered as the cursor; backend
// returns events strictly older than that.
export function useStudentTimelineOlder(
  studentId: string | null | undefined,
  before: string | null,
) {
  return useQuery<StudentTimelineEvent[]>({
    queryKey: ["admin", "students", studentId, "timeline", "before", before],
    queryFn: () =>
      api.get<StudentTimelineEvent[]>(
        `/api/v1/admin/students/${studentId}/timeline?before=${encodeURIComponent(
          before ?? "",
        )}`,
      ),
    enabled: !!studentId && !!before,
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
  url?: string | null;
  user_agent?: string | null;
  viewport_width?: number | null;
  viewport_height?: number | null;
  app_version?: string | null;
  category?: string | null;
  severity?: string | null;
  error_id?: string | null;
  recent_route_history?: string[] | null;
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
export type PulseWindow = "24h" | "7d" | "30d";

export interface PulseData {
  window: PulseWindow;
  active_students: number;
  agent_calls: number;
  avg_eval_score: number;
  new_enrollments_7d: number;
  open_feedback: number;
  // Legacy keys — only present when window=24h. Don't read these in
  // new code; window-aware components should use the unsuffixed keys.
  active_students_24h?: number;
  agent_calls_24h?: number;
  avg_eval_score_24h?: number;
}

export function useAdminPulse(window: PulseWindow = "24h") {
  return useQuery<PulseData>({
    queryKey: ["admin", "pulse", window],
    queryFn: () =>
      api.get<PulseData>(`/api/v1/admin/pulse?window=${window}`),
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

// ── Health strip (admin cockpit top-row metrics) ───────────────────
export interface HealthMetric {
  key: string;
  label: string;
  value: string;
  sub: string;
  tone: "danger" | "warn" | "ok" | "neutral";
  delta: number | null;
  delta_text: string | null;
  // Parallel backend adds a 7-day daily trend per metric. Optional so
  // the FE stays compatible while the backend rolls out — render a
  // flat baseline when this is empty/undefined.
  sparkline_7d?: number[];
}

export interface HealthStripData {
  metrics: HealthMetric[];
  generated_at: string;
}

export function useHealthStrip() {
  return useQuery<HealthStripData>({
    queryKey: ["admin", "health-strip"],
    queryFn: () => api.get<HealthStripData>("/api/v1/admin/health-strip"),
    staleTime: 60_000,
  });
}

export function useRiskPanels() {
  return useQuery<RiskPanels>({
    queryKey: ["admin", "risk-panels"],
    queryFn: () => api.get<RiskPanels>("/api/v1/admin/risk-panels"),
    // Panels recompute nightly via Celery; a 1-hour staleness is fine.
    // Manual refresh on the page covers the "I just ran the task" case.
    staleTime: 60 * 60_000,
  });
}

// ── RETENTION-V2 — Most-urgent metric strip + top-N urgent students ──
export interface MostUrgentTile {
  slip_type: string;
  label: string;
  count: number;
  description: string;
  tone: "danger" | "warn" | "info" | "neutral";
}

export interface MostUrgentStudent {
  user_id: string;
  name: string;
  email: string;
  risk_score: number;
  risk_reason: string | null;
  slip_type: string;
  days_since_last_session: number | null;
  paid: boolean;
  last_active_text: string;
  recommended_intervention: string | null;
}

export interface MostUrgentResponse {
  tiles: MostUrgentTile[];
  students: MostUrgentStudent[];
  generated_at: string;
}

export function useMostUrgentStudents(limit: number = 5) {
  return useQuery<MostUrgentResponse>({
    queryKey: ["admin", "most-urgent", limit],
    queryFn: () =>
      api.get<MostUrgentResponse>(
        `/api/v1/admin/most-urgent-students?limit=${limit}`,
      ),
    staleTime: 30_000,
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

// ── Unified admin audit log (legacy admin_audit_log + agent_actions) ──
// Powers /admin/audit-log. Separate from the legacy /audit-log endpoint
// (which returns agent_actions only). All filters are optional and
// passed through as querystring params; backend sorts desc by created_at
// and caps the result at 200 rows.
export interface AdminAuditEntry {
  id: string;
  source: "admin_audit_log" | "agent_actions";
  admin_email: string;
  action_type: string;
  resource_type: string | null;
  resource_id: string | null;
  summary: string;
  created_at: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  extra: Record<string, unknown> | null;
}

export interface AdminAuditFilters {
  admin_id?: string;
  action_type?: string;
  resource_type?: string;
  resource_id?: string;
  since?: string;
  until?: string;
}

export function useAdminAuditLog(filters: AdminAuditFilters = {}) {
  return useQuery<AdminAuditEntry[]>({
    queryKey: ["admin", "admin-audit-log", filters],
    queryFn: () => {
      const sp = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) {
        if (v != null && v !== "") sp.set(k, String(v));
      }
      const qs = sp.toString();
      return api.get<AdminAuditEntry[]>(
        `/api/v1/admin/admin-audit-log${qs ? "?" + qs : ""}`,
      );
    },
    staleTime: 30_000,
  });
}

// D16/CP3.2 — manual outreach logging (WhatsApp / phone).
// Records that the admin reached out via an external channel (their
// own WhatsApp, a phone call) so the cockpit timeline + retention
// audit see the contact even though it didn't fire through the platform.

export interface OutreachLogRow {
  id: string;
  user_id: string;
  channel: string;
  triggered_by: string;
  triggered_by_user_id: string | null;
  body_preview: string | null;
  sent_at: string;
  status: string;
}

export type ManualOutreachChannel = "whatsapp" | "phone";

export function useLogManualOutreach(studentId: string | null) {
  const queryClient = useQueryClient();
  return useMutation<
    OutreachLogRow,
    Error,
    { channel: ManualOutreachChannel; body_preview?: string }
  >({
    mutationFn: ({ channel, body_preview }) =>
      api.post<OutreachLogRow>(
        `/api/v1/admin/students/${studentId}/outreach`,
        { channel, body_preview: body_preview ?? "" },
      ),
    onSuccess: () => {
      // Invalidate timeline so the new contact surfaces immediately.
      void queryClient.invalidateQueries({
        queryKey: ["admin", "students", studentId, "timeline"],
      });
      // Invalidate the cockpit roster — the calls/events panels read
      // from the same /admin/console/v1 source.
      void queryClient.invalidateQueries({
        queryKey: ["admin", "console"],
      });
    },
  });
}

// ── Agents cockpit (3-tab reliability/quality/cost) ────────────────
export interface AgentHealthExtended {
  name: string;
  description: string;
  total_actions: number;
  actions_24h: number;
  error_count: number;
  errors_24h: number;
  avg_duration_ms: number;
  avg_duration_24h_ms: number;
  last_called_at: string | null;
  success_rate: number | null;
  avg_eval_score_24h: number | null;
  status: "healthy" | "degraded";
  is_stub: boolean;
  calls_sparkline: number[];
  eval_sparkline: (number | null)[];
  est_cost_24h_usd: number;
  model: string | null;
  // DISC-57 — per-actor-role breakdowns. Keys: student, admin, system,
  // service, unknown. The "unknown" bucket holds pre-DISC-57 historical
  // rows that didn't capture an actor.
  actions_24h_by_role: Record<string, number>;
  total_actions_by_role: Record<string, number>;
}

export interface AgentsHealthExtendedResponse {
  agents: AgentHealthExtended[];
  total_actions_24h: number;
  total_errors_24h: number;
  total_cost_24h_usd: number;
  healthy_count: number;
  degraded_count: number;
  generated_at: string;
  // DISC-57 — page-level 24h actor breakdown across all agents.
  total_actions_24h_by_role: Record<string, number>;
}

export interface AgentRecentError {
  action_id: string;
  student_id: string | null;
  student_name: string | null;
  error: string;
  input_preview: string;
  created_at: string;
  // DISC-57 — optional actor role. Backend may or may not populate
  // for this nested struct; UI degrades gracefully when missing.
  actor_role?: string | null;
}

export interface AgentSampleAction {
  action_id: string;
  student_id: string | null;
  student_name: string | null;
  input_preview: string;
  output_preview: string;
  evaluation_score: number | null;
  duration_ms: number;
  created_at: string;
  actor_role?: string | null;
}

export interface AgentDetailResponse {
  name: string;
  description: string;
  model: string | null;
  is_stub: boolean;
  prompt_content: string | null;
  prompt_path: string | null;
  actions_24h: number;
  actions_7d: number;
  actions_all_time: number;
  avg_eval_score_24h: number | null;
  avg_eval_score_7d: number | null;
  avg_duration_24h_ms: number;
  recent_errors: AgentRecentError[];
  recent_samples: AgentSampleAction[];
  est_cost_7d_usd: number;
  est_cost_total_usd: number;
  // DISC-57 — per-actor-role breakdowns across three time horizons.
  actions_24h_by_role: Record<string, number>;
  actions_7d_by_role: Record<string, number>;
  actions_all_time_by_role: Record<string, number>;
}

export interface RecentActivityRow {
  action_id: string;
  agent_name: string;
  student_id: string | null;
  student_name: string | null;
  duration_ms: number;
  evaluation_score: number | null;
  has_error: boolean;
  error_preview: string | null;
  input_preview: string;
  output_preview: string;
  created_at: string;
  // DISC-57 — who triggered this action. actor_role is one of
  // "student" | "admin" | "system" | "service" | null. actor_id is
  // the triggering user/service. on_behalf_of is set when an admin
  // or system action targeted a specific student (student_name maps
  // to that target).
  actor_role: string | null;
  actor_id: string | null;
  on_behalf_of: string | null;
}

export interface RecentActivityResponse {
  items: RecentActivityRow[];
  total_returned: number;
}

export interface RoutingHealthResponse {
  total_routes_24h: number;
  keyword_hits_24h: number;
  llm_fallback_24h: number;
  keyword_hit_rate: number;
  agent_distribution_24h: Record<string, number>;
  suspected_misroutes_24h: number;
  misroutes_by_agent: Record<string, number>;
  generated_at: string;
}

export interface AgentRuntimeConfigRead {
  name: string;
  is_enabled: boolean;
  rate_limit_per_minute: number | null;
  prompt_version: string | null;
  notes: string | null;
  updated_at: string;
  updated_by: string | null;
}

export interface RuntimeConfigListResponse {
  items: AgentRuntimeConfigRead[];
}

export interface ManualTriggerResponse {
  agent_name: string;
  status: string;
  duration_ms: number;
  response_preview: string;
  evaluation_score: number | null;
  action_id: string;
}

export function useAgentsHealthExtended() {
  return useQuery<AgentsHealthExtendedResponse>({
    queryKey: ["admin", "agents", "health-extended"],
    queryFn: () =>
      api.get<AgentsHealthExtendedResponse>(
        "/api/v1/admin/agents/health-extended",
      ),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export function useAgentDetail(agentName: string | null) {
  return useQuery<AgentDetailResponse>({
    queryKey: ["admin", "agents", "detail", agentName],
    queryFn: () =>
      api.get<AgentDetailResponse>(
        `/api/v1/admin/agents/${agentName}/detail`,
      ),
    enabled: !!agentName,
    staleTime: 30_000,
  });
}

export function useAgentRecentActivity(filters: {
  agent_name?: string;
  student_id?: string;
  min_eval_score?: number;
  limit?: number;
  // DISC-57 — narrow rows to a single actor role. Empty / undefined
  // returns all rows.
  actor_role?: string;
}) {
  return useQuery<RecentActivityResponse>({
    queryKey: ["admin", "agents", "recent-activity", filters],
    queryFn: () => {
      const sp = new URLSearchParams();
      if (filters.agent_name) sp.set("agent_name", filters.agent_name);
      if (filters.student_id) sp.set("student_id", filters.student_id);
      if (filters.min_eval_score != null)
        sp.set("min_eval_score", String(filters.min_eval_score));
      if (filters.limit != null) sp.set("limit", String(filters.limit));
      if (filters.actor_role) sp.set("actor_role", filters.actor_role);
      const qs = sp.toString();
      return api.get<RecentActivityResponse>(
        `/api/v1/admin/agents/recent-activity${qs ? "?" + qs : ""}`,
      );
    },
    staleTime: 15_000,
  });
}

export function useRoutingHealth() {
  return useQuery<RoutingHealthResponse>({
    queryKey: ["admin", "agents", "routing-health"],
    queryFn: () =>
      api.get<RoutingHealthResponse>("/api/v1/admin/agents/routing-health"),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useAgentRuntimeConfig() {
  return useQuery<RuntimeConfigListResponse>({
    queryKey: ["admin", "agents", "runtime-config"],
    queryFn: () =>
      api.get<RuntimeConfigListResponse>(
        "/api/v1/admin/agents/runtime-config",
      ),
    staleTime: 60_000,
  });
}

export function useUpdateAgentConfig() {
  const queryClient = useQueryClient();
  return useMutation<
    AgentRuntimeConfigRead,
    Error,
    {
      name: string;
      is_enabled?: boolean;
      rate_limit_per_minute?: number | null;
      prompt_version?: string | null;
      notes?: string | null;
    }
  >({
    mutationFn: ({ name, ...body }) =>
      api.patch<AgentRuntimeConfigRead>(
        `/api/v1/admin/agents/${name}/config`,
        body,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["admin", "agents", "runtime-config"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["admin", "agents", "health-extended"],
      });
    },
  });
}

// ── Task templates per agent (admin authoring) ───────────────────
export interface TaskTemplate {
  id: string;
  agent_name: string;
  label: string;
  body: string;
  is_built_in: boolean;
  sort_order: number;
  created_by_admin_id: string | null;
  created_at: string;
  updated_at: string;
}

// ── Context preview for the manual trigger panel ─────────────────
export interface ContextFactor {
  label: string;
  present: boolean;
}

export interface ContextPreviewResponse {
  agent_name: string;
  student_id: string;
  readiness_score: number; // 0..1
  tone: "ready" | "limited" | "not_ready";
  summary: string;
  factors: ContextFactor[];
  student_name: string | null;
  student_email: string | null;
  generated_at: string;
}

export function useAgentTemplates(agentName: string | null) {
  return useQuery<TaskTemplate[]>({
    queryKey: ["admin", "agents", agentName, "templates"],
    queryFn: () =>
      api.get<TaskTemplate[]>(`/api/v1/admin/agents/${agentName}/templates`),
    enabled: !!agentName,
    staleTime: 60_000,
  });
}

export function useCreateAgentTemplate() {
  const qc = useQueryClient();
  return useMutation<
    TaskTemplate,
    Error,
    { agent_name: string; label: string; body: string; sort_order?: number }
  >({
    mutationFn: (body) =>
      api.post<TaskTemplate>(`/api/v1/admin/agents/templates`, body),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({
        queryKey: ["admin", "agents", vars.agent_name, "templates"],
      });
    },
  });
}

export function useUpdateAgentTemplate() {
  const qc = useQueryClient();
  return useMutation<
    TaskTemplate,
    Error,
    {
      id: string;
      agent_name: string;
      body: { label?: string; body?: string; sort_order?: number };
    }
  >({
    mutationFn: ({ id, body }) =>
      api.patch<TaskTemplate>(`/api/v1/admin/agents/templates/${id}`, body),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({
        queryKey: ["admin", "agents", vars.agent_name, "templates"],
      });
    },
  });
}

export function useDeleteAgentTemplate() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: string; agent_name: string }>({
    mutationFn: ({ id }) =>
      api.del(`/api/v1/admin/agents/templates/${id}`),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({
        queryKey: ["admin", "agents", vars.agent_name, "templates"],
      });
    },
  });
}

export function useAgentContextPreview(
  agentName: string | null,
  studentId: string | null,
) {
  return useQuery<ContextPreviewResponse>({
    queryKey: [
      "admin",
      "agents",
      agentName,
      "context-preview",
      studentId,
    ],
    queryFn: () =>
      api.get<ContextPreviewResponse>(
        `/api/v1/admin/agents/${agentName}/context-preview?student_id=${studentId}`,
      ),
    enabled: !!agentName && !!studentId,
    staleTime: 30_000,
  });
}

// ── Send agent output to student (review-then-send) ───────────────
// Lets admins manually dispatch a triggered agent's response to the
// student through WhatsApp, email, or in-app notification. Separate
// from auto-send because the user wants to review/tweak before sending.
export interface SendAgentOutputResponse {
  outreach_id: string;
  action_id: string;
  channel: string;
  student_id: string;
  sent_at: string;
  body_preview: string;
}

export function useSendAgentOutput() {
  return useMutation<
    SendAgentOutputResponse,
    Error,
    { action_id: string; channel: string; body_override?: string; student_id?: string }
  >({
    mutationFn: ({ action_id, ...body }) =>
      api.post<SendAgentOutputResponse>(
        `/api/v1/admin/agents/actions/${action_id}/send`,
        body,
      ),
  });
}

export function useTriggerAgentManual() {
  const queryClient = useQueryClient();
  return useMutation<
    ManualTriggerResponse,
    Error,
    { agentName: string; studentId: string; task?: string }
  >({
    mutationFn: ({ agentName, studentId, task }) =>
      api.post<ManualTriggerResponse>(
        `/api/v1/admin/agents/${agentName}/trigger/v2`,
        { student_id: studentId, task },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["admin", "agents", "health-extended"],
      });
    },
  });
}

// ── Audit-log Pulse / Anomalies / audit-of-audit ───────────────────
// New 3-tab cockpit at /admin/audit-log. Endpoints are built by a
// parallel backend agent; payload schemas mirror AuditPulseResponse,
// AnomalyDetection, and the fire-and-forget `view` recorder.

export interface AuditPulseKpis {
  actions_today: number;
  actions_yesterday: number;
  distinct_admins_today: number;
  actions_per_hour_recent: number;
  actions_per_hour_baseline: number;
  anomaly_count_today: number;
}

export interface AuditPulseHourBucket {
  hour_iso: string;
  count_total: number;
  count_by_category: Record<string, number>;
}

export interface AuditPulseCategoryBreakdown {
  category: string;
  count_today: number;
  count_7d: number;
}

export interface AuditPulseTopActor {
  admin_id: string | null;
  admin_email: string;
  count_7d: number;
  last_action_at: string;
}

export interface AuditPulseTopResource {
  resource_type: string;
  resource_id: string;
  resource_label: string | null;
  count_7d: number;
}

export interface AuditPulseHotAction {
  id: string;
  admin_email: string;
  action_type: string;
  resource_type: string | null;
  resource_id: string | null;
  summary: string;
  severity: "critical" | "warn" | "info";
  created_at: string;
}

export interface AuditPulseResponse {
  kpis: AuditPulseKpis;
  hourly_sparkline: AuditPulseHourBucket[];
  categories: AuditPulseCategoryBreakdown[];
  top_actors: AuditPulseTopActor[];
  top_courses: AuditPulseTopResource[];
  top_students: AuditPulseTopResource[];
  top_agents: AuditPulseTopResource[];
  hot_critical: AuditPulseHotAction[];
  generated_at: string;
}

export interface AnomalyDetection {
  fingerprint: string;
  rule_type:
    | "burst_delete"
    | "off_hours_login"
    | "unusual_ip"
    | "first_time_action"
    | "bulk_price_change"
    | "outreach_too_short"
    | "outreach_reused"
    | "coupon_spam"
    | "agent_kill_switch";
  severity: "critical" | "warn" | "info";
  admin_id: string | null;
  admin_email: string;
  description: string;
  detected_at: string;
  window_start: string;
  window_end: string;
  audit_row_ids: string[];
  dismissed: boolean;
}

export interface AuditAnomaliesResponse {
  items: AnomalyDetection[];
  generated_at: string;
}

export function useAuditPulse() {
  return useQuery<AuditPulseResponse>({
    queryKey: ["admin", "audit", "pulse"],
    queryFn: () =>
      api.get<AuditPulseResponse>("/api/v1/admin/audit-log/pulse"),
    staleTime: 60_000,
  });
}

export function useAuditAnomalies() {
  return useQuery<AuditAnomaliesResponse>({
    queryKey: ["admin", "audit", "anomalies"],
    queryFn: () =>
      api.get<AuditAnomaliesResponse>("/api/v1/admin/audit-log/anomalies"),
    staleTime: 60_000,
  });
}

export function useDismissAnomaly() {
  const qc = useQueryClient();
  return useMutation<void, Error, { fingerprint: string; note?: string }>({
    mutationFn: ({ fingerprint, note }) =>
      api.post<void>(
        `/api/v1/admin/audit-log/anomalies/${fingerprint}/dismiss`,
        { note },
      ),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["admin", "audit", "anomalies"],
      });
      void qc.invalidateQueries({ queryKey: ["admin", "audit", "pulse"] });
    },
  });
}

export function useUndismissAnomaly() {
  const qc = useQueryClient();
  return useMutation<void, Error, { fingerprint: string }>({
    mutationFn: ({ fingerprint }) =>
      api.del(`/api/v1/admin/audit-log/anomalies/${fingerprint}/dismiss`),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["admin", "audit", "anomalies"],
      });
      void qc.invalidateQueries({ queryKey: ["admin", "audit", "pulse"] });
    },
  });
}

export function useRecordAuditView() {
  // Fire-and-forget audit-of-audit recorder. Never blocks the UI; errors
  // are swallowed silently so a logging hiccup can't break the expand
  // interaction in the Stream tab.
  return useMutation<
    void,
    Error,
    { audit_row_id: string; viewed_field: string; extra?: Record<string, unknown> }
  >({
    mutationFn: (body) =>
      api.post<void>("/api/v1/admin/audit-log/view", body),
    onError: () => {
      /* swallow */
    },
  });
}
