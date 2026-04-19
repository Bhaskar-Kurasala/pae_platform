"use client";

import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { progressApi, type ProgressResponse } from "@/lib/api-client";

const PROGRESS_CHANNEL = "progress-mutation-v1";

export function useMyProgress() {
  const queryClient = useQueryClient();
  // DISC-48 — cross-tab completions surface in real time. The default 60s
  // `staleTime` + focus refetch meant another tab's lesson completion stayed
  // invisible for up to a minute; we override the per-query staleTime and
  // subscribe to a BroadcastChannel so any tab mutation busts the cache
  // everywhere immediately.
  useEffect(() => {
    if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") {
      return;
    }
    const channel = new BroadcastChannel(PROGRESS_CHANNEL);
    channel.onmessage = () => {
      void queryClient.invalidateQueries({ queryKey: ["progress"] });
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
    };
    return () => channel.close();
  }, [queryClient]);

  return useQuery<ProgressResponse>({
    queryKey: ["progress", "mine"],
    queryFn: () => progressApi.mine(),
    staleTime: 0,
    refetchOnWindowFocus: true,
  });
}

export function useCompleteLesson() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (lessonId: string) => progressApi.complete(lessonId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["progress"] });
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
      if (typeof window !== "undefined" && typeof BroadcastChannel !== "undefined") {
        try {
          const channel = new BroadcastChannel(PROGRESS_CHANNEL);
          channel.postMessage({ type: "lesson_completed", at: Date.now() });
          channel.close();
        } catch {
          // Best-effort cross-tab signal — safe to drop.
        }
      }
    },
  });
}

export function useLessonCompleted(lessonId: string, progress: ProgressResponse | undefined) {
  return progress?.courses.some((c) =>
    c.lessons.some((l) => l.id === lessonId && l.status === "completed"),
  ) ?? false;
}
