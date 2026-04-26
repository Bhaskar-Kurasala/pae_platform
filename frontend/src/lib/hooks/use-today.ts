"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  todayApi,
  type ConsistencyResponse,
  type DailyIntention,
  type MicroWinsResponse,
  type SessionStep,
  type TodaySummaryResponse,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

export function useMyIntention() {
  return useQuery<DailyIntention | null>({
    queryKey: ["today", "intention"],
    queryFn: () => todayApi.getIntention(),
  });
}

function localIsoDate(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function useSetIntention() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => todayApi.setIntention(text, localIsoDate()),
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

export function useTodaySummary() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<TodaySummaryResponse>({
    queryKey: ["today", "summary"],
    queryFn: () => todayApi.summary(),
    enabled: isAuthed,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });
}

export function useMarkSessionStep() {
  const qc = useQueryClient();
  return useMutation<TodaySummaryResponse, Error, SessionStep>({
    mutationFn: (step) => todayApi.markStep(step),
    onSuccess: (data) => {
      qc.setQueryData(["today", "summary"], data);
    },
  });
}
