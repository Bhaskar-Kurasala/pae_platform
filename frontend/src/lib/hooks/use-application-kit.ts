"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  applicationKitApi,
  type ApplicationKitListItem,
  type ApplicationKitResponse,
  type BuildKitRequest,
} from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

export function useApplicationKits() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<ApplicationKitListItem[]>({
    queryKey: ["application-kit", "list"],
    queryFn: () => applicationKitApi.list(),
    enabled: isAuthed,
    staleTime: 30_000,
  });
}

export function useApplicationKit(id: string | null) {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  return useQuery<ApplicationKitResponse>({
    queryKey: ["application-kit", "detail", id],
    queryFn: () => applicationKitApi.get(id as string),
    enabled: isAuthed && !!id,
    staleTime: 30_000,
  });
}

export function useBuildApplicationKit() {
  const qc = useQueryClient();
  return useMutation<ApplicationKitResponse, Error, BuildKitRequest>({
    mutationFn: (req) => applicationKitApi.build(req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["application-kit", "list"] });
    },
  });
}

export function useDeleteApplicationKit() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) => applicationKitApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["application-kit", "list"] });
    },
  });
}

/**
 * Re-exported for direct use in `<a href={applicationKitDownloadUrl(id)}>` —
 * the PDF stream isn't JSON, so it can't go through the React Query layer.
 */
export const applicationKitDownloadUrl = applicationKitApi.downloadUrl;
