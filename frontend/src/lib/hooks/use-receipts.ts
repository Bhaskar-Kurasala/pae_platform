"use client";

import { useQuery } from "@tanstack/react-query";
import { receiptsApi, type GrowthSnapshot } from "@/lib/api-client";

export function useMyReceipts(limit = 12) {
  return useQuery<GrowthSnapshot[]>({
    queryKey: ["receipts", "mine", limit],
    queryFn: () => receiptsApi.listMine(limit),
    staleTime: 5 * 60 * 1000,
  });
}
