"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  promotionApi,
  type PromotionConfirmResponse,
  type PromotionSummaryResponse,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

/**
 * Single round-trip for the /promotion screen — four rungs, role transition
 * copy, and the gate status (`not_ready` / `ready_to_promote` / `promoted`).
 */
export function usePromotionSummary() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<PromotionSummaryResponse>({
    queryKey: ["promotion", "summary"],
    queryFn: () => promotionApi.summary(),
    enabled: isAuthed,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });
}

/**
 * Confirm the promotion. The backend flips `users.promoted_at` so the gate
 * is recorded; the cache patch updates the summary so the screen instantly
 * shows the promoted state without an extra round-trip.
 */
export function useConfirmPromotion() {
  const qc = useQueryClient();
  return useMutation<PromotionConfirmResponse, Error>({
    mutationFn: () => promotionApi.confirm(),
    onSuccess: (confirm) => {
      qc.setQueryData<PromotionSummaryResponse | undefined>(
        ["promotion", "summary"],
        (prev) =>
          prev
            ? {
                ...prev,
                gate_status: "promoted",
                promoted_at: confirm.promoted_at,
                promoted_to_role: confirm.promoted_to_role,
              }
            : prev,
      );
    },
  });
}
