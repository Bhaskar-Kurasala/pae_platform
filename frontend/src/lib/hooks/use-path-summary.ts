"use client";

import { useQuery } from "@tanstack/react-query";

import { pathApi, type PathSummaryResponse } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

/**
 * Single round-trip for the entire /path screen — constellation + ladder +
 * proof wall. Stale-time keeps the screen visually stable while the user
 * scrolls through the rungs without bursts of refetches.
 */
export function usePathSummary() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<PathSummaryResponse>({
    queryKey: ["path", "summary"],
    queryFn: () => pathApi.summary(),
    enabled: isAuthed,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });
}
