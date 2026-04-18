"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  reflectionsApi,
  type Reflection,
  type ReflectionInput,
} from "@/lib/api-client";

/** Returns today's reflection (null if not logged yet). */
export function useMyReflectionToday() {
  return useQuery<Reflection | null>({
    queryKey: ["reflection", "today"],
    queryFn: () => reflectionsApi.today(),
  });
}

export function useUpsertReflection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ReflectionInput) => reflectionsApi.upsert(body),
    onSuccess: (data) => {
      queryClient.setQueryData(["reflection", "today"], data);
      void queryClient.invalidateQueries({ queryKey: ["reflection"] });
    },
  });
}

export function useMyRecentReflections(limit = 30) {
  return useQuery<Reflection[]>({
    queryKey: ["reflection", "recent", limit],
    queryFn: () => reflectionsApi.recent(limit),
  });
}
