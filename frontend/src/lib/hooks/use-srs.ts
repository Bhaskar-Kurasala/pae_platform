"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { srsApi, type SRSCard } from "@/lib/api-client";

const DUE_KEY = ["srs", "due"] as const;

export function useDueCards(limit = 10) {
  return useQuery<SRSCard[]>({
    queryKey: [...DUE_KEY, limit],
    queryFn: () => srsApi.listDue(limit),
    staleTime: 30_000,
  });
}

export function useReviewCard() {
  const qc = useQueryClient();
  return useMutation<SRSCard, Error, { cardId: string; quality: number }>({
    mutationFn: ({ cardId, quality }) => srsApi.review(cardId, quality),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DUE_KEY });
    },
  });
}

export function useCreateCard() {
  const qc = useQueryClient();
  return useMutation<SRSCard, Error, { concept_key: string; prompt?: string }>({
    mutationFn: (payload) => srsApi.create(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DUE_KEY });
    },
  });
}
