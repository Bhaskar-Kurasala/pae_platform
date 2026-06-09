"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  adminAssetsApi,
  adminExercisesApi,
  type AdminAssetCreate,
  type AdminAssetOut,
  type AdminAssetUpdate,
  type AdminExerciseCreate,
  type AdminExerciseOut,
  type AdminExerciseUpdate,
  type AdminLegacySyncResponse,
} from "@/lib/admin-content-api";
import { useAuthStore } from "@/stores/auth-store";

// ── Lesson assets ────────────────────────────────────────────────

export function useAdminLessonAssets(lessonId: string | undefined) {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<AdminAssetOut[]>({
    queryKey: ["admin", "lesson-assets", lessonId],
    queryFn: () => adminAssetsApi.list(lessonId!),
    enabled: isAuthed && !!lessonId,
    staleTime: 15_000,
  });
}

export function useCreateLessonAsset(lessonId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<AdminAssetOut, Error, AdminAssetCreate>({
    mutationFn: (body) => adminAssetsApi.create(lessonId!, body),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["admin", "lesson-assets", lessonId],
      });
    },
  });
}

export function useUpdateLessonAsset(lessonId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<
    AdminAssetOut,
    Error,
    { assetId: string; body: AdminAssetUpdate }
  >({
    mutationFn: ({ assetId, body }) => adminAssetsApi.update(assetId, body),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["admin", "lesson-assets", lessonId],
      });
    },
  });
}

export function useDeleteLessonAsset(lessonId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (assetId) => adminAssetsApi.remove(assetId),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["admin", "lesson-assets", lessonId],
      });
    },
  });
}

export function useSyncLegacyAssets(lessonId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<AdminLegacySyncResponse, Error, void>({
    mutationFn: () => adminAssetsApi.syncFromLegacy(lessonId!),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["admin", "lesson-assets", lessonId],
      });
    },
  });
}

// ── Exercises ────────────────────────────────────────────────────

export function useAdminLessonExercises(lessonId: string | undefined) {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<AdminExerciseOut[]>({
    queryKey: ["admin", "lesson-exercises", lessonId],
    queryFn: () => adminExercisesApi.listForLesson(lessonId!),
    enabled: isAuthed && !!lessonId,
    staleTime: 15_000,
  });
}

export function useCreateExercise(lessonId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<AdminExerciseOut, Error, AdminExerciseCreate>({
    mutationFn: (body) => adminExercisesApi.create(lessonId!, body),
    onSuccess: () => {
      if (lessonId)
        qc.invalidateQueries({
          queryKey: ["admin", "lesson-exercises", lessonId],
        });
      qc.invalidateQueries({ queryKey: ["practice", "exercises"] });
    },
  });
}

export function useUpdateExercise(lessonId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<
    AdminExerciseOut,
    Error,
    { exerciseId: string; body: AdminExerciseUpdate }
  >({
    mutationFn: ({ exerciseId, body }) =>
      adminExercisesApi.update(exerciseId, body),
    onSuccess: () => {
      if (lessonId)
        qc.invalidateQueries({
          queryKey: ["admin", "lesson-exercises", lessonId],
        });
      qc.invalidateQueries({ queryKey: ["practice", "exercises"] });
    },
  });
}

export function useDeleteExercise(lessonId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (exerciseId) => adminExercisesApi.remove(exerciseId),
    onSuccess: () => {
      if (lessonId)
        qc.invalidateQueries({
          queryKey: ["admin", "lesson-exercises", lessonId],
        });
      qc.invalidateQueries({ queryKey: ["practice", "exercises"] });
    },
  });
}
