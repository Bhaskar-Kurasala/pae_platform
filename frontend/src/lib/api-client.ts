const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface StoredAuth {
  state?: {
    token?: string;
    refreshToken?: string;
    user?: unknown;
    isAuthenticated?: boolean;
  };
}

function readAuthStorage(): StoredAuth | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("auth-storage");
    if (!raw) return null;
    return JSON.parse(raw) as StoredAuth;
  } catch {
    return null;
  }
}

function writeTokensToStorage(accessToken: string, refreshToken: string): void {
  if (typeof window === "undefined") return;
  try {
    const parsed = readAuthStorage() ?? { state: {} };
    parsed.state = {
      ...(parsed.state ?? {}),
      token: accessToken,
      refreshToken,
      isAuthenticated: true,
    };
    localStorage.setItem("auth-storage", JSON.stringify(parsed));
  } catch {
    // ignore
  }
}

function getToken(): string | null {
  return readAuthStorage()?.state?.token ?? null;
}

function getRefreshToken(): string | null {
  return readAuthStorage()?.state?.refreshToken ?? null;
}

function sanitizeNext(raw: string | null): string | null {
  if (!raw) return null;
  // Only allow absolute same-origin paths like "/studio" or "/foo?bar=1".
  // Reject protocol-relative ("//evil.com"), cross-origin, and non-path values.
  if (!/^\/[^/]/.test(raw)) return null;
  return raw;
}

function clearAuthAndRedirect(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem("auth-storage");
  } catch {
    // ignore
  }
  const current = `${window.location.pathname}${window.location.search}`;
  const next = sanitizeNext(current);
  const loginUrl = next ? `/login?next=${encodeURIComponent(next)}` : "/login";
  window.location.replace(loginUrl);
}

let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;
  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return null;
      const data = (await res.json()) as {
        access_token: string;
        refresh_token: string;
      };
      writeTokensToStorage(data.access_token, data.refresh_token);
      return data.access_token;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  // On 401 with an existing token, attempt a single silent refresh + retry.
  // Skip for the refresh endpoint itself to avoid infinite loops.
  if (res.status === 401 && token && !path.endsWith("/auth/refresh")) {
    const fresh = await refreshAccessToken();
    if (fresh) {
      const retryHeaders = { ...headers, Authorization: `Bearer ${fresh}` };
      res = await fetch(`${API_BASE}${path}`, { ...init, headers: retryHeaders });
    }
  }

  if (!res.ok) {
    if (res.status === 401 && token) {
      clearAuthAndRedirect();
      return new Promise(() => {}); // never resolves; redirect is in-flight
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
    throw new ApiError(res.status, message, detail);
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

export interface DailyCompletion {
  date: string;
  count: number;
}

export interface ProgressResponse {
  courses: CourseProgress[];
  overall_progress: number;
  lessons_completed_total: number;
  lessons_total: number;
  exercises_completed: number;
  total_exercises: number;
  exercise_completion_rate: number;
  watch_time_minutes: number;
  completions_by_day: DailyCompletion[];
  active_course_id: string | null;
  active_course_title: string | null;
  next_lesson_id: string | null;
  next_lesson_title: string | null;
  today_unlock_percentage: number;
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
  description?: string | null;
  exercise_type: string;
  difficulty: string;
  starter_code?: string | null;
  rubric?: Record<string, unknown> | null;
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
  refresh: (body: { refresh_token: string }) =>
    api.post<TokenResponse>("/api/v1/auth/refresh", body),
  me: () => api.get<UserResponse>("/api/v1/auth/me"),
};

export interface EnrollmentResponse {
  id: string;
  student_id: string;
  course_id: string;
  status: string;
  enrolled_at: string;
  progress_pct?: number;
}

export const coursesApi = {
  list: () => api.get<CourseResponse[]>("/api/v1/courses"),
  get: (id: string) => api.get<CourseResponse>(`/api/v1/courses/${id}`),
  lessons: (courseId: string) =>
    api.get<LessonResponse[]>(`/api/v1/courses/${courseId}/lessons`),
  enroll: (id: string) =>
    api.post<EnrollmentResponse>(`/api/v1/courses/${id}/enroll`, {}),
  myEnrollment: (id: string) =>
    api.get<EnrollmentResponse | null>(`/api/v1/courses/${id}/my-enrollment`),
};

export const lessonsApi = {
  get: (id: string) => api.get<LessonResponse>(`/api/v1/lessons/${id}`),
  resources: (id: string) =>
    api.get<LessonResourceResponse[]>(`/api/v1/lessons/${id}/resources`),
};

export type ResourceKind = "notebook" | "repo" | "video" | "pdf" | "slides" | "link";

export interface LessonResourceResponse {
  id: string;
  course_id: string;
  lesson_id: string | null;
  kind: ResourceKind;
  title: string;
  description: string | null;
  order: number;
  is_required: boolean;
  metadata: Record<string, unknown> | null;
  locked: boolean;
}

export interface ResourceOpenResponse {
  kind: ResourceKind;
  open_url: string;
  expires_at: string | null;
}

export const resourcesApi = {
  forCourse: (courseId: string) =>
    api.get<LessonResourceResponse[]>(`/api/v1/courses/${courseId}/resources`),
  open: (resourceId: string) =>
    api.post<ResourceOpenResponse>(`/api/v1/resources/${resourceId}/open`, {}),
};

// DISC-21 — Stripe checkout for paid courses
export interface CheckoutResponse {
  checkout_url: string;
  session_id: string;
}

export const billingApi = {
  createCheckout: (body: {
    course_id: string;
    tier?: string;
    success_url: string;
    cancel_url: string;
  }) =>
    api.post<CheckoutResponse>("/api/v1/billing/checkout", {
      tier: "pro",
      ...body,
    }),
};

export const progressApi = {
  mine: () => api.get<ProgressResponse>("/api/v1/students/me/progress"),
  complete: (lessonId: string) =>
    api.post<LessonProgressRecord>(`/api/v1/students/me/lessons/${lessonId}/complete`, {}),
  uncomplete: (lessonId: string) =>
    api.del(`/api/v1/students/me/lessons/${lessonId}/complete`),
};

export const exercisesApi = {
  list: (limit = 50) =>
    api.get<ExerciseResponse[]>(`/api/v1/exercises?limit=${limit}`),
  get: (id: string) => api.get<ExerciseResponse>(`/api/v1/exercises/${id}`),
  getSubmission: (submissionId: string) =>
    api.get<SubmissionResponse>(
      `/api/v1/exercises/submissions/${submissionId}`,
    ),
  mySubmissions: (exerciseId: string, limit = 20) =>
    api.get<SubmissionResponse[]>(
      `/api/v1/exercises/${exerciseId}/submissions/mine?limit=${limit}`,
    ),
  getSolution: (id: string) =>
    api.get<{ solution_code: string; reason: string }>(
      `/api/v1/exercises/${id}/solution`,
    ),
  submit: (
    id: string,
    payload: {
      code: string;
      shared_with_peers?: boolean;
      share_note?: string;
      self_explanation?: string;
    },
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
  weekly_hours: string | null;
  target_role: string | null;
  days_remaining: number;
  created_at: string;
  updated_at: string;
}

export interface GoalContractInput {
  motivation: Motivation;
  deadline_months: number;
  success_statement: string;
  weekly_hours?: string | null;
  target_role?: string | null;
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
  /**
   * The persisted row id is currently NOT returned by `POST /receipts/autopsy`
   * (the route still uses the legacy `AutopsyResponse` shape). Marked optional
   * so that a future backend change adding `id` to the response is non-breaking.
   * The list/detail endpoints (`GET /receipts/autopsy[/{id}]`) DO carry `id`.
   */
  id?: string;
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

// Persistence-side rows for the Proof Portfolio view.
export interface PortfolioAutopsyListItem {
  id: string;
  project_title: string;
  headline: string;
  overall_score: number;
  created_at: string;
}

export interface PortfolioAutopsyDetailResponse {
  id: string;
  user_id: string;
  project_title: string;
  project_description: string;
  headline: string;
  overall_score: number;
  axes: Record<string, unknown>;
  what_worked: string[];
  what_to_do_differently: Record<string, unknown>[];
  production_gaps: string[];
  next_project_seed: string | null;
  created_at: string;
  updated_at: string;
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
  list: () =>
    api.get<PortfolioAutopsyListItem[]>("/api/v1/receipts/autopsy"),
  get: (id: string) =>
    api.get<PortfolioAutopsyDetailResponse>(
      `/api/v1/receipts/autopsy/${id}`,
    ),
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

// ── Practice (unified /practice surface) ─────────────────────────
export interface PracticeReviewRecord {
  id: string;
  problem_id: string | null;
  review: SeniorReview;
  created_at: string;
}

export const practiceApi = {
  review: (payload: {
    code: string;
    problem_id?: string;
    problem_context?: string;
  }) => api.post<PracticeReviewRecord>("/api/v1/practice/review", payload),
  listReviews: (problemId?: string, limit = 20) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (problemId) params.set("problem_id", problemId);
    return api.get<PracticeReviewRecord[]>(
      `/api/v1/practice/reviews?${params.toString()}`,
    );
  },
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
  answer: string;
  hint: string;
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

// ── Today surface (3A-11, 3A-14, 3A-17) ──────────────────────────
export interface DailyIntention {
  id: string;
  user_id: string;
  intention_date: string;
  text: string;
  created_at: string;
  updated_at: string;
}

export interface ConsistencyResponse {
  days_this_week: number;
  window_days: number;
}

export interface MicroWinItem {
  kind: string;
  label: string;
  occurred_at: string;
}

export interface MicroWinsResponse {
  wins: MicroWinItem[];
}

// ── Today summary (DISC: today refactor 2026-04-26) ──────────────
export interface TodayUser {
  first_name: string;
}

export interface TodayGoal {
  success_statement: string | null;
  target_role: string | null;
  days_remaining: number;
  motivation: string | null;
}

export interface TodayConsistency {
  days_active: number;
  window_days: number;
}

export interface TodayProgress {
  overall_percentage: number;
  lessons_completed_total: number;
  lessons_total: number;
  today_unlock_percentage: number;
  active_course_id: string | null;
  active_course_title: string | null;
  next_lesson_id: string | null;
  next_lesson_title: string | null;
}

export interface TodaySession {
  id: string | null;
  ordinal: number;
  started_at: string | null;
  warmup_done_at: string | null;
  lesson_done_at: string | null;
  reflect_done_at: string | null;
}

export interface TodayCurrentFocus {
  skill_slug: string | null;
  skill_name: string | null;
  skill_blurb: string | null;
}

export interface TodayCapstone {
  exercise_id: string | null;
  title: string | null;
  days_to_due: number | null;
  draft_quality: number | null;
  drafts_count: number;
}

export interface TodayMilestone {
  label: string | null;
  days: number;
}

export interface TodayReadiness {
  current: number;
  delta_week: number;
}

export interface TodayIntentionField {
  text: string | null;
}

export interface TodayCohortEventItem {
  kind: string;
  actor_handle: string;
  label: string;
  occurred_at: string;
}

export interface TodaySummaryResponse {
  user: TodayUser;
  goal: TodayGoal;
  consistency: TodayConsistency;
  progress: TodayProgress;
  session: TodaySession;
  current_focus: TodayCurrentFocus;
  capstone: TodayCapstone;
  next_milestone: TodayMilestone;
  readiness: TodayReadiness;
  intention: TodayIntentionField;
  due_card_count: number;
  peers_at_level: number;
  promotions_today: number;
  micro_wins: MicroWinItem[];
  cohort_events: TodayCohortEventItem[];
}

export type SessionStep = "warmup" | "lesson" | "reflect";

export const todayApi = {
  getIntention: () => api.get<DailyIntention | null>("/api/v1/today/intention"),
  setIntention: (text: string, intentionDate?: string) =>
    api.post<DailyIntention>("/api/v1/today/intention", {
      text,
      ...(intentionDate ? { intention_date: intentionDate } : {}),
    }),
  consistency: () =>
    api.get<ConsistencyResponse>("/api/v1/today/consistency"),
  microWins: () => api.get<MicroWinsResponse>("/api/v1/today/micro-wins"),
  summary: () => api.get<TodaySummaryResponse>("/api/v1/today/summary"),
  markStep: (step: SessionStep) =>
    api.post<TodaySummaryResponse>(`/api/v1/today/session/step/${step}`, {}),
};

// ── Retrieval quiz (3A-10) ───────────────────────────────────────
export interface RetrievalQuestion {
  id: string;
  question: string;
  options: Record<string, string>;
}

export interface RetrievalQuizResponse {
  questions: RetrievalQuestion[];
}

export interface GradedQuestion {
  mcq_id: string;
  correct: boolean;
  correct_answer: string;
  explanation: string | null;
}

export interface RetrievalQuizResult {
  correct: number;
  total: number;
  graded: GradedQuestion[];
}

export const retrievalQuizApi = {
  get: (lessonId: string) =>
    api.get<RetrievalQuizResponse>(
      `/api/v1/students/me/lessons/${lessonId}/retrieval-quiz`,
    ),
  submit: (lessonId: string, answers: Record<string, string>) =>
    api.post<RetrievalQuizResult>(
      `/api/v1/students/me/lessons/${lessonId}/retrieval-quiz`,
      { answers },
    ),
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

// ── Readiness Overview + Proof Portfolio ─────────────────────────
// Mirrors `backend/app/schemas/readiness_overview.py`. The wire is
// snake_case so the FE types preserve snake_case (no remapping here).

export interface ReadinessSubScores {
  skill: number;
  proof: number;
  interview: number;
  targeting: number;
}

export interface ReadinessNorthStarDelta {
  current: number;
  prior: number;
  delta_week: number;
}

export interface ReadinessNextAction {
  kind: string;
  route: string;
  label: string;
  payload?: Record<string, unknown> | null;
}

export interface ReadinessLatestVerdict {
  session_id: string;
  headline: string;
  next_action: ReadinessNextAction;
  created_at: string;
}

export interface ReadinessTrendPoint {
  week_start: string; // ISO date
  score: number;
}

export interface ReadinessOverviewResponse {
  user_first_name: string;
  target_role: string | null;
  overall_readiness: number;
  sub_scores: ReadinessSubScores;
  north_star: ReadinessNorthStarDelta;
  top_actions: ReadinessNextAction[];
  latest_verdict: ReadinessLatestVerdict | null;
  trend_8w: ReadinessTrendPoint[];
}

export interface ProofCapstoneArtifact {
  exercise_id: string;
  title: string;
  draft_count: number;
  last_score: number | null;
  days_since_last_edit: number | null;
}

export interface ProofAIReviewItem {
  id: string;
  problem_title: string | null;
  score: number | null;
  created_at: string;
}

export interface ProofAIReviews {
  count: number;
  last_three: ProofAIReviewItem[];
}

export interface ProofMockReport {
  session_id: string;
  headline: string | null;
  verdict: string | null;
  created_at: string;
  target_role: string | null;
}

export interface ProofAutopsy {
  id: string;
  project_title: string;
  headline: string;
  overall_score: number;
  created_at: string;
}

export interface ProofPeerReviews {
  count_received: number;
  count_given: number;
}

export interface ProofPrimaryArtifact {
  title: string | null;
  snippet: string | null;
}

export interface ProofResponse {
  capstone_artifacts: ProofCapstoneArtifact[];
  ai_reviews: ProofAIReviews;
  mock_reports: ProofMockReport[];
  autopsies: ProofAutopsy[];
  peer_reviews: ProofPeerReviews;
  last_capstone_summary: ProofPrimaryArtifact | null;
}

export const readinessOverviewApi = {
  getOverview: () =>
    api.get<ReadinessOverviewResponse>("/api/v1/readiness/overview"),
  getProof: () => api.get<ProofResponse>("/api/v1/readiness/proof"),
};

// ── Application Kit ─────────────────────────────────────────────
// Mirrors `backend/app/schemas/application_kit.py`.

export interface BuildKitRequest {
  label: string;
  target_role?: string | null;
  jd_library_id?: string | null;
  tailored_resume_id?: string | null;
  mock_session_id?: string | null;
  autopsy_id?: string | null;
}

export interface ApplicationKitListItem {
  id: string;
  label: string;
  target_role: string | null;
  status: string;
  generated_at: string | null;
  created_at: string;
  manifest_keys: string[];
}

export interface ApplicationKitResponse {
  id: string;
  label: string;
  target_role: string | null;
  status: string;
  generated_at: string | null;
  created_at: string;
  manifest: Record<string, unknown>;
  has_pdf: boolean;
}

export const applicationKitApi = {
  build: (req: BuildKitRequest) =>
    api.post<ApplicationKitResponse>("/api/v1/readiness/kit", req),
  list: () =>
    api.get<ApplicationKitListItem[]>("/api/v1/readiness/kit"),
  get: (id: string) =>
    api.get<ApplicationKitResponse>(`/api/v1/readiness/kit/${id}`),
  delete: (id: string) => api.del(`/api/v1/readiness/kit/${id}`),
  /**
   * Returns the absolute URL for the PDF stream so callers can drop it
   * into an `<a href download>` rather than fetching it through the JSON
   * `request()` helper (which assumes JSON bodies).
   */
  downloadUrl: (id: string): string =>
    `${API_BASE}/api/v1/readiness/kit/${id}/download`,
};

// ── Readiness Workspace Events ──────────────────────────────────
// Mirrors `backend/app/schemas/readiness_events.py`.

export interface RecordEventInput {
  view: string;
  event: string;
  payload?: Record<string, unknown> | null;
  session_id?: string | null;
  occurred_at?: string | null;
}

export interface RecordEventBatchResponse {
  recorded: number;
  skipped: number;
}

export interface WorkspaceEventOut {
  id: string;
  view: string;
  event: string;
  payload: Record<string, unknown> | null;
  session_id: string | null;
  occurred_at: string;
}

export interface WorkspaceEventSummaryResponse {
  total: number;
  by_view: Record<string, number>;
  by_event: Record<string, number>;
  last_event_at: string | null;
  since_days: number;
  generated_at: string;
}

export interface WorkspaceEventListOpts {
  view?: string;
  limit?: number;
}

export interface WorkspaceEventSummaryOpts {
  since_days?: number;
}

export const readinessEventsApi = {
  /**
   * Always normalizes to a wrapped batch — the backend pre-validator
   * accepts both shapes but `{events: [...]}` keeps the wire predictable.
   */
  record: (events: RecordEventInput | RecordEventInput[]) => {
    const batch = Array.isArray(events) ? events : [events];
    return api.post<RecordEventBatchResponse>(
      "/api/v1/readiness/events",
      { events: batch },
    );
  },
  list: (opts: WorkspaceEventListOpts = {}) => {
    const params = new URLSearchParams();
    if (opts.view) params.set("view", opts.view);
    if (typeof opts.limit === "number") {
      params.set("limit", String(opts.limit));
    }
    const qs = params.toString();
    return api.get<WorkspaceEventOut[]>(
      `/api/v1/readiness/events${qs ? `?${qs}` : ""}`,
    );
  },
  summary: (opts: WorkspaceEventSummaryOpts = {}) => {
    const params = new URLSearchParams();
    if (typeof opts.since_days === "number") {
      params.set("since_days", String(opts.since_days));
    }
    const qs = params.toString();
    return api.get<WorkspaceEventSummaryResponse>(
      `/api/v1/readiness/events/summary${qs ? `?${qs}` : ""}`,
    );
  },
};

// ── Catalog + Payments v2 (DISC: payments-v2 + catalog refactor 2026-04-26) ─
// Mirrors `backend/app/schemas/payments_v2.py`. Wire is snake_case so the FE
// types preserve snake_case (no remapping). UUIDs travel as strings; datetimes
// as ISO-8601 strings.

export interface CatalogBullet {
  text: string;
  included: boolean;
}

export interface CatalogCourseResponse {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  price_cents: number;
  currency: string;
  is_published: boolean;
  difficulty: string;
  bullets: CatalogBullet[];
  metadata: Record<string, unknown>;
  /** Per-user. False for anon callers. */
  is_unlocked: boolean;
}

export interface CatalogBundleResponse {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  price_cents: number;
  currency: string;
  /** UUIDs of the courses included in this bundle. */
  course_ids: string[];
  metadata: Record<string, unknown>;
  is_published: boolean;
}

export interface CatalogResponse {
  courses: CatalogCourseResponse[];
  bundles: CatalogBundleResponse[];
}

export type PaymentTargetType = "course" | "bundle";
export type PaymentProvider = "razorpay" | "stripe";

export interface CreateOrderRequest {
  target_type: PaymentTargetType;
  target_id: string;
  provider?: PaymentProvider;
  /** When omitted, the route falls back to settings.payments_default_currency. */
  currency?: string | null;
}

export interface CreateOrderResponse {
  order_id: string;
  provider: string;
  provider_order_id: string;
  amount_cents: number;
  currency: string;
  receipt_number: string;
  /** May be null in dev when the MockProvider fallback is active. */
  razorpay_key_id: string | null;
  user_email: string;
  user_name: string;
  target_title: string;
}

export interface ConfirmOrderRequest {
  razorpay_order_id?: string | null;
  razorpay_payment_id?: string | null;
  razorpay_signature?: string | null;
}

export interface ConfirmOrderResponse {
  order_id: string;
  status: string;
  paid_at: string | null;
  fulfilled_at: string | null;
  /** Course UUIDs whose entitlements were granted (may be >1 for bundles). */
  entitlements_granted: string[];
}

export interface FreeEnrollRequest {
  course_id: string;
}

export interface FreeEnrollResponse {
  course_id: string;
  entitlement_id: string;
  granted_at: string;
}

export interface PaymentAttemptItem {
  id: string;
  provider: string;
  provider_payment_id: string | null;
  amount_cents: number;
  status: string;
  failure_reason: string | null;
  attempted_at: string;
}

export interface OrderListItem {
  id: string;
  target_type: string;
  target_id: string;
  target_title: string | null;
  amount_cents: number;
  currency: string;
  status: string;
  receipt_number: string | null;
  created_at: string;
}

export interface OrderDetailResponse extends OrderListItem {
  paid_at: string | null;
  fulfilled_at: string | null;
  failure_reason: string | null;
  payment_attempts: PaymentAttemptItem[];
}

export const catalogApi = {
  // Trailing slash matters — the FastAPI route is mounted at `/catalog/`.
  get: () => api.get<CatalogResponse>("/api/v1/catalog/"),
};

export const paymentsApi = {
  createOrder: (body: CreateOrderRequest) =>
    api.post<CreateOrderResponse>("/api/v1/payments/orders", body),
  confirmOrder: (orderId: string, body: ConfirmOrderRequest) =>
    api.post<ConfirmOrderResponse>(
      `/api/v1/payments/orders/${orderId}/confirm`,
      body,
    ),
  listOrders: () =>
    api.get<OrderListItem[]>("/api/v1/payments/orders"),
  getOrder: (orderId: string) =>
    api.get<OrderDetailResponse>(`/api/v1/payments/orders/${orderId}`),
  freeEnroll: (body: FreeEnrollRequest) =>
    api.post<FreeEnrollResponse>("/api/v1/payments/free-enroll", body),
  /**
   * Returns the absolute URL for the receipt PDF stream so callers can drop
   * it into an `<a href download>` rather than fetching it through the JSON
   * `request()` helper (which assumes JSON bodies).
   */
  receiptUrl: (orderId: string): string =>
    `${API_BASE}/api/v1/payments/orders/${orderId}/receipt.pdf`,
};

export { ApiError, API_BASE, sanitizeNext };
