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

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, (detail as { detail?: string }).detail ?? res.statusText);
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

export interface ProgressResponse {
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
  created_at: string;
  updated_at: string;
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
  mine: () => api.get<ProgressResponse[]>("/api/v1/students/me/progress"),
  complete: (lessonId: string) =>
    api.post<ProgressResponse>(`/api/v1/students/me/lessons/${lessonId}/complete`, {}),
};

export const exercisesApi = {
  get: (id: string) => api.get<ExerciseResponse>(`/api/v1/exercises/${id}`),
  submit: (id: string, code: string) =>
    api.post<SubmissionResponse>(`/api/v1/exercises/${id}/submit`, { code }),
};

export { ApiError, API_BASE };
