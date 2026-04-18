const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("auth-storage");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { state?: { token?: string } };
    return parsed.state?.token ?? null;
  } catch {
    return null;
  }
}

function clearAuthAndRedirect(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem("auth-storage");
  } catch {
    // ignore
  }
  window.location.replace("/login");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    // Expired or invalid session — clear auth and redirect to login
    if (res.status === 401 && token) {
      clearAuthAndRedirect();
      return new Promise(() => {});  // never resolves; redirect is in-flight
    }
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    const raw = (detail as { detail?: unknown }).detail;
    let message: string;
    if (typeof raw === "string") {
      message = raw;
    } else if (Array.isArray(raw)) {
      message = raw
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return String(item);
        })
        .join("; ");
    } else {
      message = res.statusText;
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  del: (path: string) => request<void>(path, { method: "DELETE" }),
};

// ── Typed API calls ──────────────────────────────────────────────

export interface UserResponse {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  is_verified: boolean;
  github_username?: string;
  avatar_url?: string;
  created_at: string;
  updated_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface CourseResponse {
  id: string;
  title: string;
  slug: string;
  description?: string;
  thumbnail_url?: string;
  price_cents: number;
  is_published: boolean;
  difficulty: string;
  estimated_hours: number;
  created_at: string;
  updated_at: string;
}

export interface LessonResponse {
  id: string;
  course_id: string;
  title: string;
  slug: string;
  description?: string;
  video_url?: string;
  youtube_video_id?: string;
  duration_seconds: number;
  order: number;
  is_published: boolean;
  is_free_preview: boolean;
  created_at: string;
  updated_at: string;
}

export interface LessonProgressItem {
  id: string;
  title: string;
  order: number;
  status: string;
}

export interface CourseProgress {
  course_id: string;
  course_title: string;
  total_lessons: number;
  completed_lessons: number;
  progress_percentage: number;
  next_lesson_id: string | null;
  next_lesson_title: string | null;
  lessons: LessonProgressItem[];
}

export interface ProgressResponse {
  courses: CourseProgress[];
  overall_progress: number;
}

export interface LessonProgressRecord {
  id: string;
  student_id: string;
  lesson_id: string;
  status: string;
  watch_time_seconds: number;
  completed_at?: string;
  last_position_seconds: number;
  created_at: string;
  updated_at: string;
}

export interface ExerciseResponse {
  id: string;
  lesson_id: string;
  title: string;
  exercise_type: string;
  difficulty: string;
  points: number;
  order: number;
  created_at: string;
  updated_at: string;
}

export interface SubmissionResponse {
  id: string;
  student_id: string;
  exercise_id: string;
  status: string;
  score?: number;
  feedback?: string;
  ai_feedback?: Record<string, unknown>;
  attempt_number: number;
  shared_with_peers: boolean;
  share_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface PeerSubmissionItem {
  id: string;
  code: string | null;
  share_note: string | null;
  score: number | null;
  created_at: string;
  author_handle: string;
}

export const authApi = {
  register: (body: { email: string; full_name: string; password: string }) =>
    api.post<UserResponse>("/api/v1/auth/register", body),
  login: (body: { email: string; password: string }) =>
    api.post<TokenResponse>("/api/v1/auth/login", body),
  me: () => api.get<UserResponse>("/api/v1/auth/me"),
};

export const coursesApi = {
  list: () => api.get<CourseResponse[]>("/api/v1/courses"),
  get: (id: string) => api.get<CourseResponse>(`/api/v1/courses/${id}`),
  lessons: (courseId: string) =>
    api.get<LessonResponse[]>(`/api/v1/courses/${courseId}/lessons`),
};

export const lessonsApi = {
  get: (id: string) => api.get<LessonResponse>(`/api/v1/lessons/${id}`),
};

export const progressApi = {
  mine: () => api.get<ProgressResponse>("/api/v1/students/me/progress"),
  complete: (lessonId: string) =>
    api.post<LessonProgressRecord>(`/api/v1/students/me/lessons/${lessonId}/complete`, {}),
};

export const exercisesApi = {
  get: (id: string) => api.get<ExerciseResponse>(`/api/v1/exercises/${id}`),
  submit: (
    id: string,
    payload: { code: string; shared_with_peers?: boolean; share_note?: string },
  ) => api.post<SubmissionResponse>(`/api/v1/exercises/${id}/submit`, payload),
  peerGallery: (id: string, limit = 20) =>
    api.get<PeerSubmissionItem[]>(
      `/api/v1/exercises/${id}/peer-gallery?limit=${limit}`,
    ),
  updateShare: (
    submissionId: string,
    payload: { shared_with_peers: boolean; share_note?: string },
  ) =>
    api.patch<SubmissionResponse>(
      `/api/v1/exercises/submissions/${submissionId}/share`,
      payload,
    ),
};

// ── Goal Contract ────────────────────────────────────────────────
export type Motivation = "career_switch" | "skill_up" | "curiosity" | "interview";

export interface GoalContract {
  id: string;
  user_id: string;
  motivation: Motivation;
  deadline_months: number;
  success_statement: string;
  created_at: string;
  updated_at: string;
}

export interface GoalContractInput {
  motivation: Motivation;
  deadline_months: number;
  success_statement: string;
}

export const goalsApi = {
  mine: () => api.get<GoalContract>("/api/v1/goals/me"),
  upsert: (body: GoalContractInput) =>
    api.post<GoalContract>("/api/v1/goals/me", body),
  patch: (body: Partial<GoalContractInput>) =>
    request<GoalContract>("/api/v1/goals/me", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
};

// ── Reflections ─────────────────────────────────────────────────
export type Mood = "blocked" | "meh" | "steady" | "flowing";

export interface Reflection {
  id: string;
  user_id: string;
  reflection_date: string; // ISO date, e.g. "2026-04-18"
  mood: Mood;
  note: string;
  created_at: string;
  updated_at: string;
}

export interface ReflectionInput {
  mood: Mood;
  note?: string;
  /** Optional ISO date; defaults to server's UTC today. */
  reflection_date?: string;
}

export const reflectionsApi = {
  today: () => api.get<Reflection | null>("/api/v1/reflections/me/today"),
  recent: (limit = 30) =>
    api.get<Reflection[]>(`/api/v1/reflections/me/recent?limit=${limit}`),
  upsert: (body: ReflectionInput) =>
    api.post<Reflection>("/api/v1/reflections/me", body),
};

// ── Skills / Skill Map ─────────────────────────────────────────
export type MasteryLevel =
  | "unknown"
  | "novice"
  | "learning"
  | "proficient"
  | "mastered";
export type SkillEdgeType = "prereq" | "related";

export interface SkillNode {
  id: string;
  slug: string;
  name: string;
  description: string;
  difficulty: number;
}

export interface SkillEdge {
  from_skill_id: string;
  to_skill_id: string;
  edge_type: SkillEdgeType;
}

export interface SkillGraph {
  nodes: SkillNode[];
  edges: SkillEdge[];
}

export interface UserSkillState {
  skill_id: string;
  mastery_level: MasteryLevel;
  confidence: number;
  last_touched_at: string | null;
}

export interface SkillPath {
  motivation: Motivation | null;
  slugs: string[];
}

export const skillsApi = {
  graph: () => api.get<SkillGraph>("/api/v1/skills/graph"),
  mine: () => api.get<UserSkillState[]>("/api/v1/skills/me"),
  path: () => api.get<SkillPath>("/api/v1/skills/path"),
  touch: (skillId: string) =>
    api.post<{ skill_id: string; last_touched_at: string }>(
      `/api/v1/skills/${skillId}/touch`,
      {},
    ),
};

// ── Diagnostic ─────────────────────────────────────────────────
export interface DiagnosticQuestion {
  id: string;
  skill_slug: string;
  prompt: string;
}

export interface DiagnosticScaleItem {
  rating: number;
  label: string;
}

export interface DiagnosticBank {
  questions: DiagnosticQuestion[];
  scale: DiagnosticScaleItem[];
}

export interface DiagnosticAnswer {
  skill_slug: string;
  rating: number;
}

export const diagnosticApi = {
  questions: () => api.get<DiagnosticBank>("/api/v1/diagnostic/questions"),
  submit: (answers: DiagnosticAnswer[]) =>
    api.post<{ states_updated: number }>("/api/v1/diagnostic/submit", {
      answers,
    }),
};

// ── Execute (Studio sandbox) ───────────────────────────────────
export interface TraceEvent {
  line: number;
  locals: Record<string, string>;
}

export type QualitySeverity = "info" | "warning";

export interface QualityIssue {
  rule: string;
  severity: QualitySeverity;
  line: number;
  message: string;
}

export interface QualityReport {
  issues: QualityIssue[];
  score: number;
  summary: string;
}

export interface ExecuteResponse {
  stdout: string;
  stderr: string;
  exit_code: number;
  timed_out: boolean;
  error: string | null;
  events: TraceEvent[];
  quality: QualityReport;
}

export interface ExecuteRequest {
  code: string;
  timeout_seconds?: number;
}

export const executeApi = {
  run: (payload: ExecuteRequest) =>
    api.post<ExecuteResponse>("/api/v1/execute", payload),
};

export interface Misconception {
  code: string;
  title: string;
  line: number;
  severity: QualitySeverity;
  you_think: string;
  actually: string;
  fix_hint: string;
}

export interface MisconceptionReport {
  items: Misconception[];
  summary: string;
}

export const misconceptionsApi = {
  analyze: (code: string) =>
    api.post<MisconceptionReport>("/api/v1/misconceptions/analyze", { code }),
};

export interface InterviewProblemSummary {
  slug: string;
  title: string;
  category: string;
}

export interface InterviewStartResponse {
  session_id: string;
  problem: InterviewProblemSummary;
  prompt: string;
  started_at: string;
}

export interface InterviewAxisScore {
  score: number;
  observation: string;
}

export interface InterviewDebrief {
  overall_verdict: "strong_hire" | "lean_hire" | "on_the_fence" | "no_hire";
  headline: string;
  axes: {
    technical_depth: InterviewAxisScore;
    tradeoff_reasoning: InterviewAxisScore;
    production_awareness: InterviewAxisScore;
    communication: InterviewAxisScore;
  };
  strongest_moment: string;
  biggest_gap: string;
  next_focus: string;
}

export interface TeachBackRubricScore {
  score: number;
  evidence: string;
}

export interface TeachBackEvaluation {
  accuracy: TeachBackRubricScore;
  completeness: TeachBackRubricScore;
  beginner_clarity: TeachBackRubricScore;
  would_beginner_understand: boolean;
  missing_ideas: string[];
  best_sentence: string;
  follow_up: string;
}

export const teachBackApi = {
  evaluate: (payload: {
    concept: string;
    explanation: string;
    reference_notes?: string;
  }) =>
    api.post<TeachBackEvaluation>(
      "/api/v1/teach-back/evaluate",
      payload,
    ),
};

// ---------------- Portfolio autopsy (P2-12) ----------------

export interface AutopsyAxis {
  score: number;
  assessment: string;
}

export interface AutopsyFinding {
  issue: string;
  why_it_matters: string;
  what_to_do_differently: string;
}

export interface PortfolioAutopsy {
  headline: string;
  overall_score: number;
  architecture: AutopsyAxis;
  failure_handling: AutopsyAxis;
  observability: AutopsyAxis;
  scope_discipline: AutopsyAxis;
  what_worked: string[];
  what_to_do_differently: AutopsyFinding[];
  production_gaps: string[];
  next_project_seed: string;
}

export const portfolioAutopsyApi = {
  create: (payload: {
    project_title: string;
    project_description: string;
    code?: string;
    what_went_well_self?: string;
    what_was_hard_self?: string;
  }) =>
    api.post<PortfolioAutopsy>("/api/v1/receipts/autopsy", payload),
};

export const interviewApi = {
  problems: () =>
    api.get<InterviewProblemSummary[]>("/api/v1/interview/problems"),
  start: (problemSlug?: string) =>
    api.post<InterviewStartResponse>("/api/v1/interview/start", {
      problem_slug: problemSlug,
    }),
  debrief: (sessionId: string) =>
    api.post<InterviewDebrief>(
      `/api/v1/interview/${sessionId}/debrief`,
      {},
    ),
  abandon: (sessionId: string) =>
    api.del(`/api/v1/interview/${sessionId}`),
  // SSE streaming handled by a direct fetch in the component, since the api
  // helper assumes JSON response bodies.
  streamTurnUrl: () => `${API_BASE}/api/v1/interview/stream`,
};

export interface GrowthSnapshot {
  id: string;
  user_id: string;
  week_ending: string; // YYYY-MM-DD (Sunday UTC)
  lessons_completed: number;
  skills_touched: number;
  streak_days: number;
  top_concept: string | null;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// P3B enriched receipt types
export interface WowData {
  lessons_delta: number | null;
  lessons_trend: "up" | "down" | "flat" | "first_week";
}

export interface SkillCoverageItem {
  id: string;
  name: string;
  mastery: number;
}

export interface PortfolioItem {
  id: string;
  exercise_title: string;
  submitted_at: string;
}

export interface ReflectionSummary {
  mood_counts: Record<string, number>;
  dominant_mood: string;
}

export interface DayActivity {
  day: string;
  minutes: number;
}

export interface NextWeekSuggestion {
  skill_name: string;
  current_mastery: number;
}

export interface WeekReceipt {
  week_over_week: WowData;
  skills_touched_detail: SkillCoverageItem[];
  portfolio_items: PortfolioItem[];
  reflection_summary: ReflectionSummary;
  daily_activity: DayActivity[];
  next_week_suggestion: NextWeekSuggestion | null;
}

export const receiptsApi = {
  listMine: (limit = 12) =>
    api.get<GrowthSnapshot[]>(`/api/v1/receipts/me?limit=${limit}`),
  getCurrentWeek: () => api.get<WeekReceipt>("/api/v1/receipts/me/week"),
};

export interface AppNotification {
  id: string;
  title: string;
  body: string;
  notification_type: string;
  is_read: boolean;
  action_url: string | null;
  created_at: string;
}

export const notificationsApi = {
  listMine: (opts: { unreadOnly?: boolean; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.unreadOnly) params.set("unread_only", "true");
    params.set("limit", String(opts.limit ?? 50));
    return api.get<AppNotification[]>(
      `/api/v1/notifications/me?${params.toString()}`,
    );
  },
  markRead: (id: string) =>
    api.post<AppNotification>(`/api/v1/notifications/${id}/read`, {}),
  markAllRead: () =>
    api.post<{ marked_read: number }>("/api/v1/notifications/read-all", {}),
};

export type SeniorReviewVerdict = "approve" | "request_changes" | "comment";
export type SeniorReviewSeverity =
  | "nit"
  | "suggestion"
  | "concern"
  | "blocking";

export interface SeniorReviewComment {
  line: number;
  severity: SeniorReviewSeverity;
  message: string;
  suggested_change: string | null;
}

export interface SeniorReview {
  verdict: SeniorReviewVerdict;
  headline: string;
  strengths: string[];
  comments: SeniorReviewComment[];
  next_step: string;
}

export const seniorReviewApi = {
  request: (code: string, problemContext?: string) =>
    api.post<SeniorReview>("/api/v1/senior-review", {
      code,
      problem_context: problemContext,
    }),
};

export type TutorMode = "standard" | "socratic_strict";

export type SocraticLevel = 0 | 1 | 2 | 3;

export const SOCRATIC_LEVEL_LABELS: Record<SocraticLevel, string> = {
  0: "off",
  1: "gentle",
  2: "standard",
  3: "strict",
};

export interface UserPreferences {
  tutor_mode: TutorMode;
  socratic_level: SocraticLevel;
  ugly_draft_mode: boolean;
}

export const preferencesApi = {
  getMine: () => api.get<UserPreferences>("/api/v1/preferences/me"),
  update: (patch: Partial<UserPreferences>) =>
    api.patch<UserPreferences>("/api/v1/preferences/me", patch),
};

export interface SRSCard {
  id: string;
  concept_key: string;
  prompt: string;
  ease_factor: number;
  interval_days: number;
  repetitions: number;
  next_due_at: string;
  last_reviewed_at: string | null;
}

export const srsApi = {
  listDue: (limit = 10) =>
    api.get<SRSCard[]>(`/api/v1/srs/due?limit=${limit}`),
  create: (payload: { concept_key: string; prompt?: string }) =>
    api.post<SRSCard>("/api/v1/srs/cards", payload),
  review: (cardId: string, quality: number) =>
    api.post<SRSCard>(`/api/v1/srs/cards/${cardId}/review`, { quality }),
};

// ── Clarification pills (3A-4) ───────────────────────────────────
export interface ClarifyPill {
  key: string;
  label: string;
}

export interface ClarifyCheckResponse {
  show_pills: boolean;
  reason: string;
  pills: ClarifyPill[];
}

export interface FollowupResponse {
  pills: ClarifyPill[];
}

export const clarifyApi = {
  check: (message: string) =>
    api.post<ClarifyCheckResponse>("/api/v1/clarify/check", { message }),
  followups: (reply: string) =>
    api.post<FollowupResponse>("/api/v1/clarify/followups", { reply }),
};

export { ApiError, API_BASE };
