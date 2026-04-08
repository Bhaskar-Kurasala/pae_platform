"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { progressApi, type ProgressResponse } from "@/lib/api-client";

export function useMyProgress() {
  return useQuery<ProgressResponse[]>({
    queryKey: ["progress", "mine"],
    queryFn: () => progressApi.mine(),
  });
}

export function useCompleteLesson() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (lessonId: string) => progressApi.complete(lessonId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["progress"] });
    },
  });
}

export function useLessonCompleted(lessonId: string, progressList: ProgressResponse[]) {
  return progressList.some((p) => p.lesson_id === lessonId && p.status === "completed");
}
