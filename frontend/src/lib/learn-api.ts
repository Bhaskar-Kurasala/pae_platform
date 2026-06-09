"use client";

/**
 * Learn API surface — typed wrappers for /api/v1/learn.
 *
 * Kept separate from `api-client.ts` (the auto-generated typed surface)
 * so the lesson player can evolve without touching the central client.
 * Mirrors the `chat-api.ts` pattern.
 */

import { api } from "./api-client";

// ── Types matching backend/app/schemas/learn.py ────────────────────

export type AssetKind =
  | "learning_notebook"
  | "practice_notebook"
  | "video"
  | "capstone_brief"
  | "reading"
  | "git_repo";

export type AssetStatus = "not_started" | "in_progress" | "completed";
export type LessonLockState = "locked" | "unlocked" | "completed";

export interface AssetProgressOut {
  status: AssetStatus;
  watch_pct: number;
  last_position_seconds: number;
  watched_seconds: number;
  execution_count: number;
  executed_at: string | null;
  completed_at: string | null;
}

export interface LessonAssetOut {
  id: string;
  kind: AssetKind;
  order: number;
  title: string;
  description: string | null;
  duration_seconds: number | null;
  /** Surfaces metadata.source so player branches (e.g. youtube vs Mux). */
  source: string | null;
  progress: AssetProgressOut;
}

export interface LessonNodeOut {
  id: string;
  course_id: string;
  title: string;
  slug: string;
  order: number;
  description: string | null;
  duration_seconds: number;
  is_capstone: boolean;
  lock_state: LessonLockState;
  locked_reason: string | null;
  completion_pct: number;
  completed_at: string | null;
  assets: LessonAssetOut[];
  requires_lesson_ids: string[];
}

export interface LearnTimelineResponse {
  course_id: string;
  course_slug: string;
  course_title: string;
  is_entitled: boolean;
  lessons: LessonNodeOut[];
  capstone_unlocked: boolean;
  progress_pct: number;
}

export interface NotebookSignedUrlResponse {
  asset_id: string;
  url: string;
  expires_at: string;
  launch_url: string;
}

export interface VideoPlaybackTokenResponse {
  asset_id: string;
  playback_id: string;
  token: string;
  expires_at: string;
}

export interface AssetProgressUpdate {
  watch_pct?: number;
  watched_seconds?: number;
  last_position_seconds?: number;
  mark_executed?: boolean;
}

export interface LessonCompletionResponse {
  lesson_id: string;
  completed: boolean;
  completion_pct: number;
  newly_unlocked_lesson_ids: string[];
  blocking_reasons: string[];
}

export interface EnrolledCourseSummary {
  course_id: string;
  course_slug: string;
  course_title: string;
  progress_pct: number;
  total_lessons: number;
  completed_lessons: number;
  last_touched_at: string | null;
}

export interface ActiveCourseResponse {
  active_course_id: string | null;
  enrolled_courses: EnrolledCourseSummary[];
  /** "student" | "admin" | "instructor" — drives empty-state copy. */
  viewer_role: string | null;
}

// ── Calls ──────────────────────────────────────────────────────────

export const learnApi = {
  timeline: (courseId: string) =>
    api.get<LearnTimelineResponse>(`/api/v1/learn/courses/${courseId}/timeline`),

  notebookUrl: (assetId: string) =>
    api.get<NotebookSignedUrlResponse>(
      `/api/v1/learn/assets/${assetId}/notebook-url`,
    ),

  videoToken: (assetId: string) =>
    api.post<VideoPlaybackTokenResponse>(
      `/api/v1/learn/assets/${assetId}/video-token`,
      {},
    ),

  patchProgress: (assetId: string, body: AssetProgressUpdate) =>
    api.patch<AssetProgressOut>(
      `/api/v1/learn/assets/${assetId}/progress`,
      body,
    ),

  markLessonComplete: (lessonId: string, note?: string) =>
    api.post<LessonCompletionResponse>(
      `/api/v1/learn/lessons/${lessonId}/complete`,
      { note: note ?? null },
    ),

  activeCourse: () =>
    api.get<ActiveCourseResponse>(`/api/v1/learn/me/active-course`),
};
