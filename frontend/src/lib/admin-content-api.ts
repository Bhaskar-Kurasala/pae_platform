"use client";

/**
 * Admin content authoring API surface — lesson assets + exercises.
 *
 * Mirrors the backend at `/api/v1/admin` (admin_lesson_assets.py and
 * admin_exercises.py). Every call requires admin role; backend enforces.
 */

import { api } from "./api-client";

// ── Lesson asset types (mirror backend/app/schemas/learn.py) ─────

export type AdminAssetKind =
  | "learning_notebook"
  | "practice_notebook"
  | "video"
  | "capstone_brief"
  | "reading"
  | "git_repo";

export interface AdminAssetOut {
  id: string;
  lesson_id: string;
  kind: AdminAssetKind;
  order: number;
  title: string;
  description: string | null;
  storage_ref: string;
  duration_seconds: number | null;
  is_published: boolean;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface AdminAssetCreate {
  kind: AdminAssetKind;
  title: string;
  description?: string | null;
  storage_ref: string;
  order?: number;
  duration_seconds?: number | null;
  is_published?: boolean;
  metadata?: Record<string, unknown> | null;
}

export interface AdminAssetUpdate {
  kind?: AdminAssetKind;
  title?: string;
  description?: string | null;
  storage_ref?: string;
  order?: number;
  duration_seconds?: number | null;
  is_published?: boolean;
  metadata?: Record<string, unknown> | null;
}

export interface AdminLegacySyncResponse {
  lesson_id: string;
  created_assets: AdminAssetOut[];
  skipped_reasons: string[];
}

// ── Exercise types — these wrap the existing admin endpoints in admin.py
// (b3b_list/create/update/delete). The schemas are slightly more
// constrained than my draft: rubric is `{criteria: [...]}` shape,
// test_cases is a list of {name, input, expected_output, hidden}.

export type ExerciseDifficulty = "easy" | "medium" | "hard";

export interface AdminTestCase {
  name: string;
  input: string;
  expected_output: string;
  hidden?: boolean;
}

export interface AdminRubricCriterion {
  name: string;
  weight?: number;
  description?: string | null;
}

export interface AdminExerciseOut {
  id: string;
  lesson_id: string;
  title: string;
  description: string | null;
  exercise_type: string;
  difficulty: string;
  starter_code: string | null;
  solution_code: string | null;
  test_cases: Array<Record<string, unknown>> | null;
  rubric: Record<string, unknown> | null;
  points: number;
  order: number;
  github_template_url: string | null;
  is_capstone: boolean;
  pass_score: number;
  due_at: string | null;
  submission_count: number;
  created_at: string;
  updated_at: string;
}

export interface AdminExercisesListResponse {
  items: AdminExerciseOut[];
}

export interface AdminExerciseCreate {
  title: string;
  description?: string | null;
  exercise_type?: string;
  difficulty?: ExerciseDifficulty | string;
  starter_code?: string | null;
  solution_code?: string | null;
  test_cases?: AdminTestCase[] | null;
  rubric_criteria?: AdminRubricCriterion[] | null;
  points?: number;
  is_capstone?: boolean;
  pass_score?: number;
  due_at?: string | null;
  github_template_url?: string | null;
}

export interface AdminExerciseUpdate extends Partial<AdminExerciseCreate> {}

// ── Calls ────────────────────────────────────────────────────────

export const adminAssetsApi = {
  list: (lessonId: string) =>
    api.get<AdminAssetOut[]>(
      `/api/v1/admin/lessons/${lessonId}/assets`,
    ),
  create: (lessonId: string, body: AdminAssetCreate) =>
    api.post<AdminAssetOut>(
      `/api/v1/admin/lessons/${lessonId}/assets`,
      body,
    ),
  update: (assetId: string, body: AdminAssetUpdate) =>
    api.patch<AdminAssetOut>(
      `/api/v1/admin/lesson-assets/${assetId}`,
      body,
    ),
  remove: (assetId: string) =>
    api.del(`/api/v1/admin/lesson-assets/${assetId}`),
  syncFromLegacy: (lessonId: string) =>
    api.post<AdminLegacySyncResponse>(
      `/api/v1/admin/lessons/${lessonId}/assets/sync-from-legacy`,
      {},
    ),
};

// Wraps the existing admin.py endpoints (b3b_list/create/update/delete).
// listForLesson unwraps the {items: []} envelope so callers always work
// with a plain array.
export const adminExercisesApi = {
  listForLesson: async (lessonId: string): Promise<AdminExerciseOut[]> => {
    const res = await api.get<AdminExercisesListResponse>(
      `/api/v1/admin/lessons/${lessonId}/exercises`,
    );
    return res.items ?? [];
  },
  create: (lessonId: string, body: AdminExerciseCreate) =>
    api.post<AdminExerciseOut>(
      `/api/v1/admin/lessons/${lessonId}/exercises`,
      body,
    ),
  update: (exerciseId: string, body: AdminExerciseUpdate) =>
    api.patch<AdminExerciseOut>(
      `/api/v1/admin/exercises/${exerciseId}`,
      body,
    ),
  remove: (exerciseId: string) =>
    api.del(`/api/v1/admin/exercises/${exerciseId}`),
};
