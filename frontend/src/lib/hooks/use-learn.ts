"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import {
  learnApi,
  type AssetProgressOut,
  type AssetProgressUpdate,
  type LearnTimelineResponse,
  type LessonCompletionResponse,
  type NotebookSignedUrlResponse,
  type VideoPlaybackTokenResponse,
} from "@/lib/learn-api";
import { useAuthStore } from "@/stores/auth-store";

export function useLearnTimeline(
  courseId: string | undefined,
): UseQueryResult<LearnTimelineResponse> {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<LearnTimelineResponse>({
    queryKey: ["learn", "timeline", courseId],
    queryFn: () => learnApi.timeline(courseId!),
    enabled: isAuthed && !!courseId,
    staleTime: 30_000,
  });
}

export function useNotebookSignedUrl(assetId: string | undefined) {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<NotebookSignedUrlResponse>({
    queryKey: ["learn", "notebook-url", assetId],
    queryFn: () => learnApi.notebookUrl(assetId!),
    enabled: isAuthed && !!assetId,
    // Signed URL TTL is 5min server-side; refetch every 4min to stay
    // ahead of expiry while a student is sitting on the notebook.
    staleTime: 4 * 60_000,
    refetchInterval: 4 * 60_000,
  });
}

export function useVideoToken(assetId: string | undefined) {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<VideoPlaybackTokenResponse>({
    queryKey: ["learn", "video-token", assetId],
    queryFn: () => learnApi.videoToken(assetId!),
    enabled: isAuthed && !!assetId,
    // Mux signed token TTL is 4h; refetch every 3.5h.
    staleTime: 3.5 * 60 * 60_000,
    refetchInterval: 3.5 * 60 * 60_000,
  });
}

export function usePatchAssetProgress(courseId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<
    AssetProgressOut,
    Error,
    { assetId: string; body: AssetProgressUpdate }
  >({
    mutationFn: ({ assetId, body }) => learnApi.patchProgress(assetId, body),
    onSuccess: () => {
      if (courseId) {
        qc.invalidateQueries({ queryKey: ["learn", "timeline", courseId] });
      }
    },
  });
}

export function useMarkLessonComplete(courseId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<
    LessonCompletionResponse,
    Error,
    { lessonId: string; note?: string }
  >({
    mutationFn: ({ lessonId, note }) =>
      learnApi.markLessonComplete(lessonId, note),
    onSuccess: () => {
      if (courseId) {
        qc.invalidateQueries({ queryKey: ["learn", "timeline", courseId] });
      }
    },
  });
}
