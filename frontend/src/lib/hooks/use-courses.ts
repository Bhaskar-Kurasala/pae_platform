"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, coursesApi, lessonsApi, type CourseResponse, type LessonResponse } from "@/lib/api-client";

export interface CourseHealth {
  course_id: string;
  title: string;
  slug: string;
  difficulty: string;
  price_cents: number;
  is_published: boolean;
  lessons_count: number;
  enrollments: number;
  completion_rate: number;
  avg_confusion_rate: number;
  open_feedback_count: number;
  negative_feedback_count: number;
  needs_attention: boolean;
  updated_at: string;
}

export interface CoursesHealthResponse {
  items: CourseHealth[];
  generated_at: string;
}

export function useCourses() {
  return useQuery<CourseResponse[]>({
    queryKey: ["courses"],
    queryFn: () => coursesApi.list(),
  });
}

export function useCourse(id: string) {
  return useQuery<CourseResponse>({
    queryKey: ["courses", id],
    queryFn: () => coursesApi.get(id),
    enabled: !!id,
  });
}

export function useCourseLessons(courseId: string) {
  return useQuery<LessonResponse[]>({
    queryKey: ["courses", courseId, "lessons"],
    queryFn: () => coursesApi.lessons(courseId),
    enabled: !!courseId,
  });
}

export function useLesson(id: string) {
  return useQuery<LessonResponse>({
    queryKey: ["lessons", id],
    queryFn: () => lessonsApi.get(id),
    enabled: !!id,
  });
}

export function useCoursesHealth() {
  return useQuery<CoursesHealthResponse>({
    queryKey: ["admin", "courses-health"],
    queryFn: () => api.get<CoursesHealthResponse>("/api/v1/admin/courses-health"),
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------------------
// Coupons
// ---------------------------------------------------------------------------

export interface Coupon {
  id: string;
  code: string;
  course_id: string | null;
  bundle_id: string | null;
  percent_off: number;
  max_redemptions: number | null;
  redemption_count: number;
  expires_at: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CouponCreateBody {
  code: string;
  course_id?: string | null;
  bundle_id?: string | null;
  percent_off: number;
  max_redemptions?: number | null;
  expires_at?: string | null;
}

export interface CouponUpdateBody {
  percent_off?: number;
  max_redemptions?: number | null;
  expires_at?: string | null;
  is_active?: boolean;
}

export function useAllCoupons() {
  return useQuery<Coupon[]>({
    queryKey: ["admin", "coupons"],
    queryFn: () => api.get<Coupon[]>("/api/v1/admin/coupons"),
    staleTime: 30_000,
  });
}

export function useCourseCoupons(courseId: string | null) {
  return useQuery<Coupon[]>({
    queryKey: ["admin", "courses", courseId, "coupons"],
    queryFn: () => api.get<Coupon[]>(`/api/v1/admin/courses/${courseId}/coupons`),
    enabled: Boolean(courseId),
    staleTime: 30_000,
  });
}

export function useCreateCoupon() {
  const qc = useQueryClient();
  return useMutation<Coupon, Error, CouponCreateBody>({
    mutationFn: (body) => api.post<Coupon>("/api/v1/admin/coupons", body),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["admin", "courses-health"] });
      qc.invalidateQueries({ queryKey: ["admin", "coupons"] });
      if (vars.course_id) {
        qc.invalidateQueries({
          queryKey: ["admin", "courses", vars.course_id, "coupons"],
        });
      }
      if (vars.bundle_id) {
        qc.invalidateQueries({ queryKey: ["admin", "bundles"] });
      }
    },
  });
}

export function useUpdateCoupon() {
  const qc = useQueryClient();
  return useMutation<
    Coupon,
    Error,
    { couponId: string; body: CouponUpdateBody }
  >({
    mutationFn: ({ couponId, body }) =>
      api.patch<Coupon>(`/api/v1/admin/coupons/${couponId}`, body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["admin", "coupons"] });
      if (data.course_id) {
        qc.invalidateQueries({
          queryKey: ["admin", "courses", data.course_id, "coupons"],
        });
      }
    },
  });
}

export function useDeleteCoupon() {
  const qc = useQueryClient();
  return useMutation<
    void,
    Error,
    { couponId: string; courseId?: string | null }
  >({
    mutationFn: ({ couponId }) =>
      api.del(`/api/v1/admin/coupons/${couponId}`),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["admin", "coupons"] });
      if (vars.courseId) {
        qc.invalidateQueries({
          queryKey: ["admin", "courses", vars.courseId, "coupons"],
        });
      }
    },
  });
}

// ---------------------------------------------------------------------------
// Bundles
// ---------------------------------------------------------------------------

export interface BundleCourseRef {
  id: string;
  slug: string;
  title: string;
  price_cents: number;
}

export interface BundleSummary {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  price_cents: number;
  currency: string;
  course_ids: string[];
  course_count: number;
  is_published: boolean;
  sort_order: number;
  updated_at: string;
  expanded_courses?: BundleCourseRef[];
}

export interface BundleCreateBody {
  slug: string;
  title: string;
  description?: string | null;
  price_cents: number;
  currency?: string;
  course_ids: string[];
  is_published?: boolean;
  sort_order?: number;
}

export interface BundleUpdateBody {
  slug?: string;
  title?: string;
  description?: string | null;
  price_cents?: number;
  currency?: string;
  course_ids?: string[];
  is_published?: boolean;
  sort_order?: number;
}

export function useBundles() {
  return useQuery<{ items: BundleSummary[] }>({
    queryKey: ["admin", "bundles"],
    queryFn: () =>
      api.get<{ items: BundleSummary[] }>(
        "/api/v1/admin/bundles?include_courses=true",
      ),
    staleTime: 30_000,
  });
}

export function useCreateBundle() {
  const qc = useQueryClient();
  return useMutation<BundleSummary, Error, BundleCreateBody>({
    mutationFn: (body) =>
      api.post<BundleSummary>("/api/v1/admin/bundles", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "bundles"] });
    },
  });
}

export function useUpdateBundle() {
  const qc = useQueryClient();
  return useMutation<
    BundleSummary,
    Error,
    { bundleId: string; body: BundleUpdateBody }
  >({
    mutationFn: ({ bundleId, body }) =>
      api.patch<BundleSummary>(`/api/v1/admin/bundles/${bundleId}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "bundles"] });
    },
  });
}

export function useDeleteBundle() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (bundleId) => api.del(`/api/v1/admin/bundles/${bundleId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "bundles"] });
    },
  });
}

export function useAddCourseToBundle() {
  const qc = useQueryClient();
  return useMutation<
    BundleSummary,
    Error,
    { bundleId: string; courseId: string }
  >({
    mutationFn: ({ bundleId, courseId }) =>
      api.post<BundleSummary>(
        `/api/v1/admin/bundles/${bundleId}/courses/${courseId}`,
        {},
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "bundles"] });
    },
  });
}

export function useRemoveCourseFromBundle() {
  const qc = useQueryClient();
  return useMutation<
    void,
    Error,
    { bundleId: string; courseId: string }
  >({
    mutationFn: ({ bundleId, courseId }) =>
      api.del(`/api/v1/admin/bundles/${bundleId}/courses/${courseId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "bundles"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Admin Deep Course Workspace — Lessons / Exercises / MCQs / Analytics
// ---------------------------------------------------------------------------

export interface AdminLessonRead {
  id: string;
  course_id: string;
  title: string;
  slug: string;
  description: string | null;
  content: string | null;
  video_url: string | null;
  youtube_video_id: string | null;
  duration_seconds: number;
  order: number;
  is_published: boolean;
  is_free_preview: boolean;
  github_branch: string | null;
  exercise_count: number;
  mcq_count: number;
  created_at: string;
  updated_at: string;
}

export interface AdminLessonCreate {
  title: string;
  slug?: string;
  description?: string;
  content?: string;
  video_url?: string;
  youtube_video_id?: string;
  duration_seconds?: number;
  is_published?: boolean;
  is_free_preview?: boolean;
  github_branch?: string;
}

export interface AdminLessonUpdate {
  title?: string;
  slug?: string;
  description?: string | null;
  content?: string | null;
  video_url?: string | null;
  youtube_video_id?: string | null;
  duration_seconds?: number;
  is_published?: boolean;
  is_free_preview?: boolean;
  github_branch?: string | null;
}

export interface RubricCriterion {
  name: string;
  weight: number;
  description: string | null;
}

export interface TestCase {
  name: string;
  input: string;
  expected_output: string;
  hidden: boolean;
}

export interface AdminExerciseRead {
  id: string;
  lesson_id: string;
  title: string;
  description: string | null;
  exercise_type: string;
  difficulty: string;
  starter_code: string | null;
  solution_code: string | null;
  test_cases: TestCase[] | null;
  rubric: { criteria: RubricCriterion[] } | null;
  points: number;
  order: number;
  is_capstone: boolean;
  pass_score: number;
  due_at: string | null;
  github_template_url: string | null;
  submission_count: number;
  created_at: string;
  updated_at: string;
}

export interface AdminExerciseCreate {
  title: string;
  description?: string;
  exercise_type?: string;
  difficulty?: string;
  starter_code?: string;
  solution_code?: string;
  test_cases?: TestCase[];
  rubric_criteria?: RubricCriterion[];
  points?: number;
  is_capstone?: boolean;
  pass_score?: number;
  due_at?: string | null;
  github_template_url?: string;
}

export interface AdminExerciseUpdate {
  title?: string;
  description?: string;
  exercise_type?: string;
  difficulty?: string;
  starter_code?: string;
  solution_code?: string;
  test_cases?: TestCase[];
  rubric_criteria?: RubricCriterion[];
  points?: number;
  is_capstone?: boolean;
  pass_score?: number;
  due_at?: string | null;
  github_template_url?: string;
}

export interface AdminMCQRead {
  id: string;
  lesson_id: string | null;
  question: string;
  options: Record<string, string>;
  correct_answer: string;
  explanation: string | null;
  difficulty: string;
  tags: string[] | null;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface AdminMCQCreate {
  question: string;
  options: Record<string, string>;
  correct_answer: string;
  explanation?: string;
  difficulty?: string;
  tags?: string[];
}

export interface AdminMCQUpdate {
  question?: string;
  options?: Record<string, string>;
  correct_answer?: string;
  explanation?: string | null;
  difficulty?: string;
  tags?: string[] | null;
}

export interface CourseAnalyticsTopStudent {
  student_id: string;
  name: string;
  email: string;
  progress_pct: number;
  completed_at: string | null;
  last_active_at: string | null;
}

export interface CourseAnalyticsFeedback {
  id: string;
  route: string | null;
  body: string;
  category: string | null;
  sentiment: string | null;
  severity: string | null;
  resolved: boolean;
  created_at: string;
  student_name: string | null;
}

export interface CourseAnalyticsAgentActivity {
  action_id: string;
  agent_name: string;
  student_id: string;
  student_name: string | null;
  input_preview: string | null;
  output_preview: string | null;
  evaluation_score: number | null;
  has_error: boolean;
  created_at: string;
}

export interface CourseAnalyticsResponse {
  course_id: string;
  title: string;
  slug: string;
  enrolled_count: number;
  completion_count: number;
  completion_rate: number;
  avg_progress_pct: number;
  avg_confusion_rate: number;
  lesson_count: number;
  exercise_count: number;
  mcq_count: number;
  top_students: CourseAnalyticsTopStudent[];
  recent_feedback: CourseAnalyticsFeedback[];
  recent_agent_activity: CourseAnalyticsAgentActivity[];
  enrollments_last_30d: number;
  enrollments_prior_30d: number;
  enrollments_delta_pct: number;
  generated_at: string;
}

export interface CourseMCQSummary {
  counts: Record<string, number>;
  total: number;
}

// ----- Lessons -----

export function useAdminCourseLessons(courseId: string) {
  return useQuery<{ items: AdminLessonRead[] }>({
    queryKey: ["admin", "courses", courseId, "lessons"],
    queryFn: () =>
      api.get<{ items: AdminLessonRead[] }>(
        `/api/v1/admin/courses/${courseId}/lessons`,
      ),
    enabled: !!courseId,
  });
}

export function useCreateLesson() {
  const qc = useQueryClient();
  return useMutation<
    AdminLessonRead,
    Error,
    { courseId: string; body: AdminLessonCreate }
  >({
    mutationFn: ({ courseId, body }) =>
      api.post<AdminLessonRead>(
        `/api/v1/admin/courses/${courseId}/lessons`,
        body,
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({
        queryKey: ["admin", "courses", vars.courseId, "lessons"],
      });
      qc.invalidateQueries({ queryKey: ["admin", "courses-health"] });
    },
  });
}

export function useUpdateLesson() {
  const qc = useQueryClient();
  return useMutation<
    AdminLessonRead,
    Error,
    { id: string; courseId: string; patch: AdminLessonUpdate }
  >({
    mutationFn: ({ id, patch }) =>
      api.patch<AdminLessonRead>(`/api/v1/admin/lessons/${id}`, patch),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({
        queryKey: ["admin", "courses", vars.courseId, "lessons"],
      });
      qc.invalidateQueries({ queryKey: ["admin", "courses-health"] });
    },
  });
}

export function useDeleteLesson() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: string; courseId: string }>({
    mutationFn: ({ id }) => api.del(`/api/v1/admin/lessons/${id}`),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({
        queryKey: ["admin", "courses", vars.courseId, "lessons"],
      });
      qc.invalidateQueries({ queryKey: ["admin", "courses-health"] });
    },
  });
}

export function useReorderLessons() {
  const qc = useQueryClient();
  return useMutation<
    { items: AdminLessonRead[] },
    Error,
    { courseId: string; lesson_ids: string[] }
  >({
    mutationFn: ({ courseId, lesson_ids }) =>
      api.post<{ items: AdminLessonRead[] }>(
        `/api/v1/admin/courses/${courseId}/lessons/reorder`,
        { lesson_ids },
      ),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({
        queryKey: ["admin", "courses", vars.courseId, "lessons"],
      });
    },
  });
}

// ----- Exercises -----

export function useAdminLessonExercises(lessonId: string | null) {
  return useQuery<{ items: AdminExerciseRead[] }>({
    queryKey: ["admin", "lessons", lessonId, "exercises"],
    queryFn: () =>
      api.get<{ items: AdminExerciseRead[] }>(
        `/api/v1/admin/lessons/${lessonId}/exercises`,
      ),
    enabled: !!lessonId,
  });
}

export function useCreateExercise() {
  const qc = useQueryClient();
  return useMutation<
    AdminExerciseRead,
    Error,
    { lessonId: string; body: AdminExerciseCreate }
  >({
    mutationFn: ({ lessonId, body }) =>
      api.post<AdminExerciseRead>(
        `/api/v1/admin/lessons/${lessonId}/exercises`,
        body,
      ),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({
        queryKey: ["admin", "lessons", vars.lessonId, "exercises"],
      });
    },
  });
}

export function useUpdateExercise() {
  const qc = useQueryClient();
  return useMutation<
    AdminExerciseRead,
    Error,
    { id: string; lessonId: string; patch: AdminExerciseUpdate }
  >({
    mutationFn: ({ id, patch }) =>
      api.patch<AdminExerciseRead>(`/api/v1/admin/exercises/${id}`, patch),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({
        queryKey: ["admin", "lessons", vars.lessonId, "exercises"],
      });
    },
  });
}

export function useDeleteExercise() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: string; lessonId: string }>({
    mutationFn: ({ id }) => api.del(`/api/v1/admin/exercises/${id}`),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({
        queryKey: ["admin", "lessons", vars.lessonId, "exercises"],
      });
    },
  });
}

export function useReorderExercises() {
  const qc = useQueryClient();
  return useMutation<
    AdminExerciseRead[],
    Error,
    { lessonId: string; exercise_ids: string[] }
  >({
    mutationFn: ({ lessonId, exercise_ids }) =>
      api.post<AdminExerciseRead[]>(
        `/api/v1/admin/lessons/${lessonId}/exercises/reorder`,
        { exercise_ids },
      ),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({
        queryKey: ["admin", "lessons", vars.lessonId, "exercises"],
      });
    },
  });
}

// ----- MCQs -----

export function useAdminLessonMCQs(lessonId: string | null) {
  return useQuery<{ items: AdminMCQRead[]; total: number }>({
    queryKey: ["admin", "lessons", lessonId, "mcqs"],
    queryFn: () =>
      api.get<{ items: AdminMCQRead[]; total: number }>(
        `/api/v1/admin/lessons/${lessonId}/mcqs`,
      ),
    enabled: !!lessonId,
  });
}

export function useCreateMCQ() {
  const qc = useQueryClient();
  return useMutation<
    AdminMCQRead,
    Error,
    { lessonId: string; courseId?: string; body: AdminMCQCreate }
  >({
    mutationFn: ({ lessonId, body }) =>
      api.post<AdminMCQRead>(`/api/v1/admin/lessons/${lessonId}/mcqs`, body),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({
        queryKey: ["admin", "lessons", vars.lessonId, "mcqs"],
      });
      if (vars.courseId) {
        qc.invalidateQueries({
          queryKey: ["admin", "courses", vars.courseId, "mcq-summary"],
        });
      }
    },
  });
}

export function useUpdateMCQ() {
  const qc = useQueryClient();
  return useMutation<
    AdminMCQRead,
    Error,
    {
      id: string;
      lessonId: string;
      courseId?: string;
      patch: AdminMCQUpdate;
    }
  >({
    mutationFn: ({ id, patch }) =>
      api.patch<AdminMCQRead>(`/api/v1/admin/mcqs/${id}`, patch),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({
        queryKey: ["admin", "lessons", vars.lessonId, "mcqs"],
      });
      if (vars.courseId) {
        qc.invalidateQueries({
          queryKey: ["admin", "courses", vars.courseId, "mcq-summary"],
        });
      }
    },
  });
}

export function useDeleteMCQ() {
  const qc = useQueryClient();
  return useMutation<
    void,
    Error,
    { id: string; lessonId: string; courseId?: string }
  >({
    mutationFn: ({ id }) => api.del(`/api/v1/admin/mcqs/${id}`),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({
        queryKey: ["admin", "lessons", vars.lessonId, "mcqs"],
      });
      if (vars.courseId) {
        qc.invalidateQueries({
          queryKey: ["admin", "courses", vars.courseId, "mcq-summary"],
        });
      }
    },
  });
}

// ----- Analytics -----

export function useCourseAnalytics(courseId: string) {
  return useQuery<CourseAnalyticsResponse>({
    queryKey: ["admin", "courses", courseId, "analytics"],
    queryFn: () =>
      api.get<CourseAnalyticsResponse>(
        `/api/v1/admin/courses/${courseId}/analytics`,
      ),
    enabled: !!courseId,
    staleTime: 30_000,
  });
}

export function useCourseMCQSummary(courseId: string) {
  return useQuery<CourseMCQSummary>({
    queryKey: ["admin", "courses", courseId, "mcq-summary"],
    queryFn: () =>
      api.get<CourseMCQSummary>(
        `/api/v1/admin/courses/${courseId}/mcq-summary`,
      ),
    enabled: !!courseId,
  });
}
