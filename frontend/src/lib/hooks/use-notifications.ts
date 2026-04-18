"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notificationsApi, type AppNotification } from "@/lib/api-client";

export function useMyNotifications(
  opts: { unreadOnly?: boolean; limit?: number } = {},
) {
  return useQuery<AppNotification[]>({
    queryKey: ["notifications", "mine", opts.unreadOnly ?? false, opts.limit ?? 50],
    queryFn: () => notificationsApi.listMine(opts),
    staleTime: 60 * 1000,
  });
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["notifications", "mine"] });
    },
  });
}
