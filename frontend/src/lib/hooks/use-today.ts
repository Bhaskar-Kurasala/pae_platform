"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  todayApi,
  type ConsistencyResponse,
  type DailyIntention,
  type MicroWinsResponse,
} from "@/lib/api-client";

export function useMyIntention() {
  return useQuery<DailyIntention | null>({
    queryKey: ["today", "intention"],
    queryFn: () => todayApi.getIntention(),
  });
}

export function useSetIntention() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => todayApi.setIntention(text),
    onSuccess: (data) => {
      qc.setQueryData(["today", "intention"], data);
    },
  });
}

export function useConsistency() {
  return useQuery<ConsistencyResponse>({
    queryKey: ["today", "consistency"],
    queryFn: () => todayApi.consistency(),
  });
}

export function useMicroWins() {
  return useQuery<MicroWinsResponse>({
    queryKey: ["today", "micro-wins"],
    queryFn: () => todayApi.microWins(),
  });
}
