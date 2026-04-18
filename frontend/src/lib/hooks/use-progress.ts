"use client";

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { progressApi, type ProgressResponse, type LessonProgressItem } from "@/lib/api-client";

export function useMyProgress() {
  return useQuery<ProgressResponse>({
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

export function useLessonCompleted(lessonId: string, progress: ProgressResponse | undefined) {
  return progress?.courses.some((c) =>
    c.lessons.some((l) => l.id === lessonId && l.status === "completed"),
  ) ?? false;
}
