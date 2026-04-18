"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  preferencesApi,
  type UserPreferences,
} from "@/lib/api-client";

export function useMyPreferences() {
  return useQuery<UserPreferences>({
    queryKey: ["preferences", "mine"],
    queryFn: () => preferencesApi.getMine(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useUpdatePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<UserPreferences>) =>
      preferencesApi.update(patch),
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: ["preferences", "mine"] });
      const prev = qc.getQueryData<UserPreferences>(["preferences", "mine"]);
      if (prev) {
        qc.setQueryData<UserPreferences>(["preferences", "mine"], {
          ...prev,
          ...patch,
        });
      }
      return { prev };
    },
    onError: (_err, _patch, ctx) => {
      if (ctx?.prev) {
        qc.setQueryData(["preferences", "mine"], ctx.prev);
      }
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["preferences", "mine"] });
    },
  });
}
