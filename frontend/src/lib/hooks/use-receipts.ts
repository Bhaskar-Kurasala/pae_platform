"use client";

import { useQuery } from "@tanstack/react-query";
import { receiptsApi, type GrowthSnapshot, type WeekReceipt } from "@/lib/api-client";

export function useMyReceipts(limit = 12) {
  return useQuery<GrowthSnapshot[]>({
    queryKey: ["receipts", "mine", limit],
    queryFn: () => receiptsApi.listMine(limit),
    staleTime: 5 * 60 * 1000,
  });
}

export function useCurrentWeekReceipt() {
  return useQuery<WeekReceipt>({
    queryKey: ["receipts", "week"],
    queryFn: () => receiptsApi.getCurrentWeek(),
    staleTime: 5 * 60 * 1000,
  });
}
