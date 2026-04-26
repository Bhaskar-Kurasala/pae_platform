"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  portfolioAutopsyApi,
  type PortfolioAutopsy,
  type PortfolioAutopsyDetailResponse,
  type PortfolioAutopsyListItem,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

interface CreateAutopsyArgs {
  project_title: string;
  project_description: string;
  code?: string;
  what_went_well_self?: string;
  what_was_hard_self?: string;
}

export function useAutopsyList() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<PortfolioAutopsyListItem[]>({
    queryKey: ["autopsy", "list"],
    queryFn: () => portfolioAutopsyApi.list(),
    enabled: isAuthed,
    staleTime: 30_000,
  });
}

export function useAutopsyDetail(id: string | null) {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<PortfolioAutopsyDetailResponse>({
    queryKey: ["autopsy", "detail", id],
    queryFn: () => portfolioAutopsyApi.get(id as string),
    enabled: isAuthed && !!id,
    staleTime: 30_000,
  });
}

export function useCreateAutopsy() {
  const qc = useQueryClient();
  return useMutation<PortfolioAutopsy, Error, CreateAutopsyArgs>({
    mutationFn: (payload) => portfolioAutopsyApi.create(payload),
    onSuccess: () => {
      // A new autopsy bumps the proof score → invalidate the proof + overview
      // aggregators alongside the autopsy list so the workspace re-paints.
      qc.invalidateQueries({ queryKey: ["autopsy", "list"] });
      qc.invalidateQueries({ queryKey: ["readiness", "proof"] });
      qc.invalidateQueries({ queryKey: ["readiness", "overview"] });
    },
  });
}
