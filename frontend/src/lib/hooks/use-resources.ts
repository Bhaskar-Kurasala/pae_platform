"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  resourcesApi,
  type LessonResourceResponse,
  type ResourceOpenResponse,
} from "@/lib/api-client";

export function useCourseResources(courseId: string) {
  return useQuery<LessonResourceResponse[]>({
    queryKey: ["courses", courseId, "resources"],
    queryFn: () => resourcesApi.forCourse(courseId),
    enabled: !!courseId,
  });
}

export function useOpenResource() {
  return useMutation<ResourceOpenResponse, Error, string>({
    mutationFn: (resourceId: string) => resourcesApi.open(resourceId),
  });
}
