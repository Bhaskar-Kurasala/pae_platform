"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  goalsApi,
  type GoalContract,
  type GoalContractInput,
} from "@/lib/api-client";

export function useMyGoal() {
  return useQuery<GoalContract | null>({
    queryKey: ["goal", "mine"],
    queryFn: async () => {
      try {
        return await goalsApi.mine();
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
    retry: (failureCount, err) => {
      if (err instanceof ApiError && err.status === 404) return false;
      return failureCount < 2;
    },
  });
}

export function useUpsertGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: GoalContractInput) => goalsApi.upsert(body),
    onSuccess: (data) => {
      queryClient.setQueryData(["goal", "mine"], data);
      void queryClient.invalidateQueries({ queryKey: ["goal"] });
    },
  });
}

export function usePatchGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<GoalContractInput>) => goalsApi.patch(body),
    onSuccess: (data) => {
      queryClient.setQueryData(["goal", "mine"], data);
      void queryClient.invalidateQueries({ queryKey: ["goal"] });
    },
  });
}
