"use client";

import { useQuery } from "@tanstack/react-query";
import { coursesApi, lessonsApi, type CourseResponse, type LessonResponse } from "@/lib/api-client";

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
