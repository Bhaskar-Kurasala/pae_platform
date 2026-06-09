"use client";

import { useQuery } from "@tanstack/react-query";
import {
  readinessOverviewApi,
  type ProofResponse,
  type ReadinessOverviewResponse,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

export function useReadinessOverview() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<ReadinessOverviewResponse>({
    queryKey: ["readiness", "overview"],
    queryFn: () => readinessOverviewApi.getOverview(),
    enabled: isAuthed,
    staleTime: 30_000,
  });
}

export function useReadinessProof() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<ProofResponse>({
    queryKey: ["readiness", "proof"],
    queryFn: () => readinessOverviewApi.getProof(),
    enabled: isAuthed,
    staleTime: 30_000,
  });
}
